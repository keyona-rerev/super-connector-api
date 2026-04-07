"""
enricher.py — Network Activation Enrichment Engine

Given a contact record, this module:
1. Researches the contact and their org via Claude + web_search
2. Drafts a plain-text outreach email from Keyona that:
   - Opens with a warm, specific observation about their work
   - Briefly explains why she's reaching out in terms of her own work as a connector
   - Shows a structured verification block of what SC has on them
   - Asks them to reply with any corrections (one simple instruction)
3. The verification block is machine-parseable on reply — each field is on its own line
   prefixed with a label so the GAS reply scanner can extract edits cleanly

The email is NOT a pitch for Super Connector. It is a relationship-opening move
grounded in genuine information gathering and transparency.

Called by POST /bucket/{bucket_id}/enrich in main.py.
Replies are processed by NetworkActivation.gs in the Phoebe GAS project.
"""

import os
import json
import time
from typing import Optional


def _get_client():
    """Lazily instantiate the Anthropic client to avoid startup failures."""
    import anthropic
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ── VERIFICATION BLOCK BUILDER ────────────────────────────────────────────────

def build_verification_block(contact: dict, enrichment: dict) -> str:
    """
    Build the structured plain-text block that goes in the email.
    Each field is prefixed with a label on its own line.
    The GAS reply parser looks for these exact prefixes to extract edits.

    Format:
    ---
    SC_CONTACT_ID: C1234
    Name: Jane Smith
    Role: Managing Director
    Organization: gener8tor
    About your org: ...
    About you: ...
    How we connected: LinkedIn
    ---
    """
    contact_id = contact.get("contact_id", "")
    name = contact.get("full_name", "") or ""
    role = contact.get("title_role", "") or ""
    org = contact.get("organization", "") or ""
    how_we_met = contact.get("how_we_met", "") or ""
    org_desc = enrichment.get("org_description", "") or ""
    person_summary = enrichment.get("person_summary", "") or ""

    lines = ["---", f"SC_CONTACT_ID: {contact_id}"]
    lines.append(f"Name: {name}")
    if role:
        lines.append(f"Role: {role}")
    if org:
        lines.append(f"Organization: {org}")
    if org_desc:
        lines.append(f"About your org: {org_desc}")
    if person_summary:
        lines.append(f"About you: {person_summary}")
    lines.append(f"How we connected: {how_we_met}" if how_we_met else "How we connected: LinkedIn")
    lines.append("---")

    return "\n".join(lines)


# ── RESEARCH ──────────────────────────────────────────────────────────────────

def research_contact(contact: dict) -> dict:
    """
    Use Claude + web_search to gather public information about a contact.
    Focuses on the organization first, then any public profile on the person.
    Returns a dict with enrichment fields including a conversation_hook.
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
            "conversation_hook": "",
            "enrichment_status": "skipped_no_data"
        }

    prompt = f"""You are a relationship intelligence researcher building outreach context.

Contact:
- Name: {name}
- Organization: {org}
- Role: {role}
- Existing notes: {existing_notes}

Search for this person and their organization. Focus on:
1. What the organization does — mission, focus area, programs they run, who they serve
2. Any public information about this specific person — background, talks, writing, notable work
3. One specific recent thing (program launch, cohort, announcement, award) that would make a natural conversation hook

Return ONLY a JSON object with these exact keys:
{{
  "org_description": "2-3 sentences describing the organization clearly and specifically",
  "org_type": "Accelerator / VC / Incubator / Nonprofit / Venture Studio / Foundation / etc.",
  "org_focus": "primary domain or mission of the org in 5-10 words",
  "org_recent_activity": "one specific recent thing worth mentioning, or empty string if nothing found",
  "person_summary": "what is publicly known about this person specifically — not generic role description",
  "person_public_profile": "their LinkedIn URL or most relevant public profile URL, else empty string",
  "research_summary": "1 paragraph briefing — org context plus person context, specific enough to open a real conversation",
  "conversation_hook": "the single most natural and specific thing to reference in an outreach email — a program, a cohort, a recent announcement, or their background. Be concrete.",
  "enrichment_status": "enriched"
}}

Return only the JSON. No markdown fences, no preamble."""

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1400,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = ""
        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                result_text = block.text.strip()

        clean = result_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip().rstrip("```").strip()

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
            "conversation_hook": "",
            "enrichment_status": f"error: {str(e)}"
        }


# ── EMAIL DRAFTING ────────────────────────────────────────────────────────────

def draft_outreach_email(contact: dict, enrichment: dict, campaign_context: str) -> str:
    """
    Draft a plain-text outreach email from Keyona.

    What this email IS:
    - A warm, specific opening that references something real about their work
    - A brief note on why Keyona is reaching out (her work as a connector, not a pitch)
    - A structured verification block showing what she has on them
    - One clear ask: reply to correct anything that's off

    What this email is NOT:
    - A pitch for Super Connector or any product
    - A generic cold email
    - Something that requires the recipient to do anything complex
    """
    name = contact.get("full_name", "")
    first_name = name.split()[0] if name else "there"
    org = contact.get("organization", "") or ""
    role = contact.get("title_role", "") or ""
    hook = enrichment.get("conversation_hook", "")
    research_summary = enrichment.get("research_summary", "")
    verification_block = build_verification_block(contact, enrichment)

    prompt = f"""You are writing an email for Keyona Meeks, a multi-venture founder and connector based in Birmingham, Alabama.

Who Keyona is:
- Founder of ReRev Labs (AI education and automation consulting)
- Co-founder of Prismm (digital vault for community banks and credit unions)
- Co-manages Black Tech Capital (climate tech nano VC)
- Runs the DO GOOD X accelerator
- Regularly makes introductions between founders, investors, and operators across her network

Why she is reaching out (the actual purpose, in plain terms):
{campaign_context}

Contact she is writing to:
- Name: {name}
- Role: {role}
- Organization: {org}

What Keyona knows about this person (from research):
{research_summary}

The most specific, natural thing to reference about their work:
{hook}

Verification block to include verbatim in the email (paste exactly, do not change anything):
{verification_block}

Write the email now. Follow these rules exactly:

1. SUBJECT LINE first, then blank line, then body.
2. Open with 1-2 sentences that reference the hook specifically. Show you actually know something about their work. Do not be vague.
3. 2-3 sentences explaining why you're reaching out in terms of your own work. This is about being a connector who is building her network intentionally, not about any product.
4. One transition sentence into the verification block. Something like: "As I organize my network, here's what I have captured about you. Reply and let me know if anything is off."
5. Paste the verification block exactly as written above, preserving every line and label.
6. One closing sentence. Keep it natural and brief.
7. Sign off as: Keyona

Absolute rules:
- No em-dashes anywhere in the email
- No "I hope this email finds you well" or any equivalent opener
- No mention of "Super Connector" by name
- No exclamation points
- Plain text only
- Short paragraphs
- Under 200 words total in the email body, not counting the verification block"""

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
    Full pipeline: research the contact, build verification block, draft email.
    Returns enrichment data, the verification block, and the email draft.
    """
    enrichment = research_contact(contact)
    verification_block = build_verification_block(contact, enrichment)
    draft = draft_outreach_email(contact, enrichment, campaign_context)

    return {
        "contact_id": contact.get("contact_id", ""),
        "full_name": contact.get("full_name", ""),
        "organization": contact.get("organization", ""),
        "enrichment": enrichment,
        "verification_block": verification_block,
        "email_draft": draft,
    }
