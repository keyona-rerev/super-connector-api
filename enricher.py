"""
enricher.py — Network Activation Enrichment Engine

Two-pass pipeline:
  Pass 1 (org pass): research each unique organization once via Haiku + web_search,
                     store results in Railway org table, return org cache dict keyed by org name
  Pass 2 (contact pass): for each contact, read cached org data + research the person only,
                          then draft the outreach email — all in a single Haiku call

Called by POST /bucket/{bucket_id}/enrich in main.py.
Replies processed by NetworkActivation.gs in the Phoebe GAS project.

Model: claude-haiku-4-5-20251001 for all Claude calls (cost efficiency + rate limit management)
"""

import os
import json
import re
import time
from typing import Optional


HAIKU_MODEL = "claude-haiku-4-5-20251001"
SLEEP_BETWEEN_CONTACTS = 15  # seconds between individual contact calls


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
    text = re.sub(r'<cite[^>]*>(.*?)</cite>', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
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


def _parse_json_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON from a Claude response."""
    clean = strip_citations(raw).strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else clean
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip().rstrip("```").strip()
    return json.loads(clean)


# ── VERIFICATION BLOCK BUILDER ────────────────────────────────────────────────

def build_verification_block(contact: dict, enrichment: dict) -> str:
    """
    Build the structured plain-text block that goes in the email.
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


# ── PASS 1: ORG RESEARCH ──────────────────────────────────────────────────────

def research_org(org_name: str, sample_role: str = "") -> dict:
    """
    Research a single organization via Haiku + web_search.
    Called once per unique org in Pass 1. Returns cleaned org data dict.
    """
    if not org_name:
        return {
            "org_description": "", "org_type": "", "org_focus": "",
            "org_recent_activity": "", "enrichment_status": "skipped_no_org"
        }

    prompt = f"""You are a relationship intelligence researcher.

Research this organization and return ONLY a valid JSON object. No markdown, no preamble, no citation tags.

Organization: {org_name}
Context role: {sample_role}

Return exactly:
{{
  "org_description": "2-3 sentences describing what this organization does, its mission, and who it serves",
  "org_type": "Accelerator / VC / Incubator / Nonprofit / Venture Studio / Foundation / Corporate / University / Government / Other",
  "org_focus": "primary domain or mission in 5-10 words",
  "org_recent_activity": "one specific recent announcement, program launch, or cohort from the last 6 months — empty string if nothing found",
  "enrichment_status": "enriched"
}}"""

    try:
        client = _get_client()
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=600,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )
        result_text = ""
        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                result_text = block.text.strip()

        org_data = _parse_json_response(result_text)
        return clean_enrichment(org_data)

    except Exception as e:
        return {
            "org_description": "", "org_type": "", "org_focus": "",
            "org_recent_activity": "", "enrichment_status": f"error: {str(e)}"
        }


def enrich_org_pass(contacts: list) -> dict:
    """
    Pass 1: Deduplicate organizations across all contacts, research each once.
    Returns org_cache dict keyed by lowercase org name.

    Usage: org_cache = enrich_org_pass(contacts)
    Then pass org_cache into enrich_and_draft() for each contact.
    """
    org_cache = {}
    seen_orgs = {}

    # Deduplicate: collect unique org names and a sample role for context
    for contact in contacts:
        org = (contact.get("organization") or "").strip()
        role = (contact.get("title_role") or "").strip()
        if org and org.lower() not in seen_orgs:
            seen_orgs[org.lower()] = {"org_name": org, "sample_role": role}

    total = len(seen_orgs)
    for i, (org_key, org_info) in enumerate(seen_orgs.items()):
        org_name = org_info["org_name"]
        sample_role = org_info["sample_role"]

        print(f"[Org Pass] {i+1}/{total}: researching {org_name}")
        org_data = research_org(org_name, sample_role)
        org_cache[org_key] = org_data

        # Sleep between org calls to stay under rate limits (except after last one)
        if i < total - 1:
            time.sleep(SLEEP_BETWEEN_CONTACTS)

    return org_cache


# ── PASS 2: CONTACT RESEARCH + DRAFT (SINGLE COMBINED CALL) ──────────────────

def enrich_and_draft(contact: dict, campaign_context: str, org_cache: dict = None) -> dict:
    """
    Pass 2: Research the individual contact + draft the outreach email in a single Haiku call.
    Reads org context from org_cache if available — no repeat org research.

    Args:
        contact: contact dict from Railway
        campaign_context: the outreach campaign context string
        org_cache: dict keyed by lowercase org name, from enrich_org_pass()
    """
    name = contact.get("full_name", "") or ""
    first_name = name.split()[0] if name else "there"
    org = (contact.get("organization") or "").strip()
    role = (contact.get("title_role") or "").strip()
    how_we_met = contact.get("how_we_met", "") or "LinkedIn"
    existing_notes = contact.get("notes", "") or ""
    if "[Enriched" in existing_notes:
        existing_notes = existing_notes[:existing_notes.index("[Enriched")].strip()

    # Pull cached org data if available
    org_data = {}
    if org_cache and org.lower() in org_cache:
        org_data = org_cache[org.lower()]

    org_description = org_data.get("org_description", "")
    org_type = org_data.get("org_type", "")
    org_focus = org_data.get("org_focus", "")
    org_recent_activity = org_data.get("org_recent_activity", "")

    prompt = f"""You are a relationship intelligence assistant for Keyona Meeks, a multi-venture founder and connector based in Birmingham, Alabama.

Keyona's background:
- Founder of ReRev Labs (AI education and automation consulting)
- Co-founder of Prismm (digital vault for community banks and credit unions)
- Co-manages Black Tech Capital (climate tech nano VC)
- Runs DO GOOD X accelerator
- Regularly makes introductions between founders, investors, and operators

Campaign context for this outreach:
{campaign_context}

Contact to research and write for:
- Name: {name}
- Role: {role}
- Organization: {org}
- How we met: {how_we_met}
- Existing notes: {existing_notes[:200] if existing_notes else "none"}

Organization context already researched (do not re-research the org):
- Description: {org_description or "not available"}
- Type: {org_type or "not available"}
- Focus: {org_focus or "not available"}
- Recent activity: {org_recent_activity or "not available"}

Your tasks:
1. Search the web for public information about {name} specifically (not the org — that's done)
2. Using everything above, produce a single JSON object with these exact keys:

{{
  "org_description": "{org_description or 'use the org context above'}",
  "org_type": "{org_type or ''}",
  "org_focus": "{org_focus or ''}",
  "org_recent_activity": "{org_recent_activity or ''}",
  "person_summary": "what is publicly known about {name} — background, notable work, recent activity",
  "person_public_profile": "LinkedIn URL or relevant profile URL, else empty string",
  "research_summary": "1 paragraph combining org and person context for outreach use",
  "conversation_hook": "the single most concrete and specific thing to reference in an opening line — prefer something about {name} personally or {org}'s recent activity",
  "enrichment_status": "enriched",
  "email_subject": "a plain-text email subject line, no exclamation points, referencing the hook or org",
  "email_body": "the full email body only (no subject line here). Rules: plain text, no markdown, no em-dashes, no exclamation points, no 'I hope this finds you well', do not name the tool 'Super Connector', under 200 words, sign off as Keyona. Open with the hook. 2-3 sentences on being an intentional connector and why you're reaching out. One sentence transitioning to the verification block. Then paste this verification block exactly as written below. Then one brief closing sentence."
}}

Verification block to paste verbatim inside email_body after the transition sentence:
---
SC_CONTACT_ID: {contact.get("contact_id", "")}
Name: {name}
Role: {role}
Organization: {org}
About your org: {org_description or "[org description here]"}
About you: [you will fill this from your person research]
How we connected: {how_we_met or "LinkedIn"}
---

Return ONLY the JSON object. No markdown fences, no preamble, no citation tags."""

    try:
        client = _get_client()
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1800,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = ""
        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                result_text = block.text.strip()

        parsed = _parse_json_response(result_text)
        enrichment = clean_enrichment(parsed)

        # Build final verification block with actual person_summary filled in
        final_enrichment = {
            "org_description": enrichment.get("org_description", org_description),
            "org_type": enrichment.get("org_type", org_type),
            "org_focus": enrichment.get("org_focus", org_focus),
            "org_recent_activity": enrichment.get("org_recent_activity", org_recent_activity),
            "person_summary": enrichment.get("person_summary", ""),
            "person_public_profile": enrichment.get("person_public_profile", ""),
            "research_summary": enrichment.get("research_summary", ""),
            "conversation_hook": enrichment.get("conversation_hook", ""),
            "enrichment_status": enrichment.get("enrichment_status", "enriched"),
        }

        verification_block = build_verification_block(contact, final_enrichment)

        # Reconstruct email with proper verification block
        email_subject = strip_citations(enrichment.get("email_subject", ""))
        email_body = strip_citations(enrichment.get("email_body", ""))
        email_draft = f"SUBJECT: {email_subject}\n\n{email_body}" if email_subject else email_body

        return {
            "contact_id": contact.get("contact_id", ""),
            "full_name": name,
            "organization": org,
            "enrichment": final_enrichment,
            "verification_block": verification_block,
            "email_draft": email_draft,
        }

    except Exception as e:
        return {
            "contact_id": contact.get("contact_id", ""),
            "full_name": name,
            "organization": org,
            "enrichment": {
                "org_description": org_description, "org_type": org_type,
                "org_focus": org_focus, "org_recent_activity": org_recent_activity,
                "person_summary": "", "person_public_profile": "",
                "research_summary": "", "conversation_hook": "",
                "enrichment_status": f"error: {str(e)}"
            },
            "verification_block": build_verification_block(contact, org_data),
            "email_draft": f"[Draft failed: {str(e)}]",
        }
