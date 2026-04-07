"""
enricher.py — Network Activation Enrichment Engine

Given a contact record, this module:
1. Researches the contact and their org via Claude + web_search
2. Drafts a plain-text outreach email from Keyona
3. Returns enrichment data and the email draft

Called by POST /bucket/{bucket_id}/enrich in main.py.
Replies processed by NetworkActivation.gs in the Phoebe GAS project.
"""

import os
import json
import re
from typing import Optional


def _get_client():
    """Lazily instantiate the Anthropic client to avoid startup failures."""
    import anthropic
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ── CITATION STRIPPER ─────────────────────────────────────────────────────────

def strip_citations(text: str) -> str:
    """
    Remove any <cite ...>...</cite> tags and other XML/HTML artifacts that
    Claude's web search tool sometimes injects into text responses.
    Also strips bare HTML tags and cleans up extra whitespace.
    """
    if not text:
        return text
    # Remove <cite index="...">...</cite> blocks (keep the inner text)
    text = re.sub(r'<cite[^>]*>(.*?)</cite>', r'\1', text, flags=re.DOTALL)
    # Remove any remaining HTML/XML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Collapse multiple spaces/newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def clean_enrichment(enrichment: dict) -> dict:
    """Apply strip_citations to all string fields in an enrichment dict."""
    string_fields = [
        "org_description", "org_type", "org_focus", "org_recent_activity",
        "person_summary", "person_public_profile", "research_summary", "conversation_hook"
    ]
    cleaned = dict(enrichment)
    for field in string_fields:
        if field in cleaned and isinstance(cleaned[field], str):
            cleaned[field] = strip_citations(cleaned[field])
    return cleaned


# ── VERIFICATION BLOCK BUILDER ────────────────────────────────────────────────

def build_verification_block(contact: dict, enrichment: dict) -> str:
    """
    Build the structured plain-text block that goes in the email.
    Each field is prefixed with a label on its own line.
    The GAS reply parser looks for these exact prefixes to extract edits.
    """
    contact_id = contact.get("contact_id", "")
    name = contact.get("full_name", "") or ""
    role = contact.get("title_role", "") or ""
    org = contact.get("organization", "") or ""
    how_we_met = contact.get("how_we_met", "") or ""
    org_desc = strip_citations(enrichment.get("org_description", "") or "")
    person_summary = strip_citations(enrichment.get("person_summary", "") or "")

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
    Returns a cleaned dict with no citation artifacts.
    """
    name = contact.get("full_name", "")
    org = contact.get("organization", "")
    role = contact.get("title_role", "")
    existing_notes = contact.get("notes", "") or ""
    # Don't pass existing enrichment notes back into the prompt
    if "[Enriched" in existing_notes:
        existing_notes = existing_notes[:existing_notes.index("[Enriched")].strip()

    if not org and not name:
        return {
            "org_description": "", "org_type": "", "org_focus": "",
            "org_recent_activity": "", "person_summary": "", "person_public_profile": "",
            "research_summary": "", "conversation_hook": "", "enrichment_status": "skipped_no_data"
        }

    prompt = f"""You are a relationship intelligence researcher building outreach context.

Contact:
- Name: {name}
- Organization: {org}
- Role: {role}
- Existing notes: {existing_notes[:300] if existing_notes else 'none'}

Search for this person and their organization. Focus on:
1. What the organization does — mission, programs, who they serve
2. Public information about this person — background, talks, notable work
3. One specific recent thing (program launch, cohort, announcement) for a natural conversation hook

Return ONLY a valid JSON object with these exact keys. No markdown, no preamble, no citation tags:
{{
  "org_description": "2-3 sentences describing the organization",
  "org_type": "Accelerator / VC / Incubator / Nonprofit / Venture Studio / Foundation / etc.",
  "org_focus": "primary domain or mission in 5-10 words",
  "org_recent_activity": "one specific recent thing, or empty string",
  "person_summary": "what is publicly known about this person specifically",
  "person_public_profile": "LinkedIn URL or relevant profile URL, else empty string",
  "research_summary": "1 paragraph briefing combining org and person context",
  "conversation_hook": "the single most concrete thing to reference in outreach",
  "enrichment_status": "enriched"
}}"""

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

        # Strip any citation artifacts from the raw text before JSON parsing
        result_text = strip_citations(result_text)

        clean = result_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip().rstrip("```").strip()

        enrichment = json.loads(clean)
        # Strip citations from all fields after parsing too
        return clean_enrichment(enrichment)

    except Exception as e:
        return {
            "org_description": "", "org_type": "", "org_focus": "",
            "org_recent_activity": "", "person_summary": "", "person_public_profile": "",
            "research_summary": "", "conversation_hook": "",
            "enrichment_status": f"error: {str(e)}"
        }


# ── EMAIL DRAFTING ────────────────────────────────────────────────────────────

def draft_outreach_email(contact: dict, enrichment: dict, campaign_context: str) -> str:
    """
    Draft a plain-text outreach email from Keyona.
    Uses cleaned enrichment data — no citation artifacts.
    """
    name = contact.get("full_name", "")
    first_name = name.split()[0] if name else "there"
    org = contact.get("organization", "") or ""
    role = contact.get("title_role", "") or ""
    hook = strip_citations(enrichment.get("conversation_hook", "") or "")
    research_summary = strip_citations(enrichment.get("research_summary", "") or "")
    verification_block = build_verification_block(contact, enrichment)

    prompt = f"""You are writing an email for Keyona Meeks, a multi-venture founder and connector based in Birmingham, Alabama.

Who Keyona is:
- Founder of ReRev Labs (AI education and automation consulting)
- Co-founder of Prismm (digital vault for community banks and credit unions)
- Co-manages Black Tech Capital (climate tech nano VC)
- Runs the DO GOOD X accelerator
- Regularly makes introductions between founders, investors, and operators

Why she is reaching out:
{campaign_context}

Contact:
- Name: {name}
- Role: {role}
- Organization: {org}

Research summary (clean text, use as context only):
{research_summary}

Best conversation hook:
{hook}

Verification block (paste verbatim, do not alter):
{verification_block}

Write the email:
1. SUBJECT: line first, then blank line, then body
2. Open with 1-2 sentences referencing the hook specifically
3. 2-3 sentences on why you're reaching out — about being an intentional connector
4. One sentence transitioning to the verification block
5. Paste the verification block exactly
6. One brief closing sentence
7. Sign: Keyona

Rules: no em-dashes, no exclamation points, no "I hope this finds you well", no mention of "Super Connector", plain text only, under 200 words not counting the verification block"""

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
                result = strip_citations(block.text.strip())
        return result
    except Exception as e:
        return f"[Draft failed: {str(e)}]"


# ── FULL PIPELINE ─────────────────────────────────────────────────────────────

def enrich_and_draft(contact: dict, campaign_context: str) -> dict:
    """
    Full pipeline: research, clean, build verification block, draft email.
    All output is guaranteed free of citation artifacts.
    """
    enrichment = research_contact(contact)  # already cleaned
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
