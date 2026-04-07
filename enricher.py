"""
enricher.py — Network Activation Enrichment Engine

Given a contact record and a campaign context, this module:
1. Builds a research prompt targeting the org and person's public presence
2. Calls Claude with web_search to gather public info
3. Returns an enriched profile dict + a personalized outreach email draft

Called by the /bucket/{bucket_id}/enrich endpoint in main.py.

NOTE: Anthropic client is instantiated lazily inside each function call, not at module
level. This prevents startup failures if ANTHROPIC_API_KEY is not set at boot time.
"""

import os
import json
import time
from typing import Optional


def _get_client():
    """Lazily instantiate the Anthropic client to avoid startup failures."""
    import anthropic
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ── RESEARCH ──────────────────────────────────────────────────────────────────

def research_contact(contact: dict) -> dict:
    """
    Use Claude + web_search to gather public information about a contact.
    Focuses on the organization first, then any public profile on the person.
    Returns a dict with enrichment fields.
    """
    name = contact.get("full_name", "")
    org = contact.get("organization", "")
    role = contact.get("title_role", "")
    existing_notes = contact.get("notes", "")

    if not org and not name:
        return {
            "org_description": "",
            "org_type": "",
            "org_focus": "",
            "org_recent_activity": "",
            "person_summary": "",
            "person_public_profile": "",
            "research_summary": "",
            "enrichment_status": "skipped_no_data"
        }

    prompt = f"""You are a relationship intelligence researcher helping build a warm outreach profile.

Contact details:
- Name: {name}
- Organization: {org}
- Role: {role}
- Notes already captured: {existing_notes}

Please research this contact and their organization using web search. Focus on:
1. What the organization does, its mission, stage, and recent activity
2. Any public information about this person — their background, public writing, talks, or work
3. What makes them notable or interesting in their space

Return your findings as a JSON object with these exact keys:
{{
  "org_description": "2-3 sentence description of the organization",
  "org_type": "e.g. Accelerator / VC / Nonprofit / Startup / Foundation / etc.",
  "org_focus": "the primary domain or mission of the org",
  "org_recent_activity": "any recent news, programs, or announcements (or empty string if none found)",
  "person_summary": "what is publicly known about this person — their background, work, notable projects",
  "person_public_profile": "URL of their LinkedIn, website, or most relevant public profile if found, else empty string",
  "research_summary": "a single paragraph summary combining the org and person context — written as if briefing someone before a meeting",
  "enrichment_status": "enriched"
}}

Return only the JSON object. No markdown, no preamble."""

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        # Extract the final text block (Claude's answer after tool use)
        result_text = ""
        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                result_text = block.text.strip()

        # Parse JSON from result
        clean = result_text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        enrichment = json.loads(clean)
        return enrichment

    except Exception as e:
        return {
            "org_description": "",
            "org_type": "",
            "org_focus": "",
            "org_recent_activity": "",
            "person_summary": "",
            "person_public_profile": "",
            "research_summary": "",
            "enrichment_status": f"error: {str(e)}"
        }


# ── OUTREACH DRAFTING ─────────────────────────────────────────────────────────

def draft_outreach_email(contact: dict, enrichment: dict, campaign_context: str) -> str:
    """
    Draft a personalized outreach email for a contact using their enriched profile
    and the campaign context provided by Keyona.

    Voice guidelines:
    - No em-dashes
    - First-person, conversational but professional
    - Short paragraphs
    - Not overly formatted
    """
    name = contact.get("full_name", "")
    first_name = name.split()[0] if name else "there"
    org = contact.get("organization", "")
    role = contact.get("title_role", "")
    org_desc = enrichment.get("org_description", "")
    person_summary = enrichment.get("person_summary", "")
    research_summary = enrichment.get("research_summary", "")

    known_fields = []
    if name:
        known_fields.append(f"Name: {name}")
    if role:
        known_fields.append(f"Role: {role}")
    if org:
        known_fields.append(f"Organization: {org}")
    if org_desc:
        known_fields.append(f"About your org: {org_desc}")
    if person_summary:
        known_fields.append(f"About you: {person_summary}")
    how_we_met = contact.get("how_we_met", "")
    if how_we_met:
        known_fields.append(f"How we connected: {how_we_met}")

    known_block = "\n".join(f"  - {f}" for f in known_fields)

    prompt = f"""You are writing an outreach email on behalf of Keyona Meeks, a multi-venture founder based in Birmingham, Alabama.

About Keyona:
- She runs ReRev Labs (AI education, consulting, and automation)
- She co-founded Prismm (a digital vault for banks and credit unions)
- She co-manages Black Tech Capital (a climate tech nano VC)
- She operates the DO GOOD X accelerator
- She is a connector who regularly introduces founders, operators, and investors to each other

Campaign context for this email:
{campaign_context}

Contact being reached:
- Name: {name}
- Role: {role}
- Organization: {org}

Research gathered:
{research_summary}

Information Super Connector currently has on this person:
{known_block}

Write an outreach email from Keyona to {first_name}. The email should:
1. Open with a warm, direct intro — not generic
2. Reference something specific about their org or work to show this is not a mass email
3. Briefly introduce the campaign context in a way that is relevant to them specifically
4. Include a "here's what I have about you" section showing the fields above and asking them to confirm or correct the information
5. Close with a simple, low-friction call to action

Voice rules:
- No em-dashes anywhere in the email
- Short paragraphs
- Warm but not gushing
- Direct, not salesy
- First person as Keyona
- No "I hope this email finds you well" or similar filler openers

Format the output as:
SUBJECT: [subject line]

[email body]

Return only the subject line and email body. No commentary."""

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        result = ""
        for block in response.content:
            if hasattr(block, "text"):
                result = block.text.strip()
        return result
    except Exception as e:
        return f"[Draft failed: {str(e)}]"


# ── FULL PIPELINE ─────────────────────────────────────────────────────────────

def enrich_and_draft(contact: dict, campaign_context: str) -> dict:
    """
    Full pipeline: research the contact, then draft a personalized email.
    Returns a dict with enrichment data and the email draft.
    """
    enrichment = research_contact(contact)
    draft = draft_outreach_email(contact, enrichment, campaign_context)

    return {
        "contact_id": contact.get("contact_id", ""),
        "full_name": contact.get("full_name", ""),
        "organization": contact.get("organization", ""),
        "enrichment": enrichment,
        "email_draft": draft,
    }
