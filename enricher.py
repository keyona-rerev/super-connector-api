"""
enricher.py — Network Activation Enrichment Engine

Two-pass pipeline:
  Pass 1 (org pass): research each unique organization once via Haiku + web_search,
                     store results in Railway org table, auto-assign organization_id
                     to ALL matching contacts across Railway (not just the current bucket)
  Pass 2 (contact pass): for each contact, read cached org data + research the person,
                          populate what_i_can_offer and what_they_offer_me using
                          title-aware reasoning — NO email draft generated here.
                          Drafts are on-demand via /contact/{id}/draft-outreach.

Model: claude-haiku-4-5-20251001 for all Claude calls
"""

import os
import json
import re
import time
from typing import Optional


HAIKU_MODEL = "claude-haiku-4-5-20251001"
SLEEP_BETWEEN_CONTACTS = 15  # seconds between individual contact calls


def _get_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ── CITATION STRIPPER ─────────────────────────────────────────────────────────

def strip_citations(text: str) -> str:
    if not text:
        return text
    text = re.sub(r'<cite[^>]*>(.*?)</cite>', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def clean_enrichment(enrichment: dict) -> dict:
    string_fields = [
        "org_description", "org_type", "org_focus", "org_recent_activity",
        "person_summary", "person_public_profile", "research_summary",
        "conversation_hook", "what_i_can_offer", "what_they_offer_me"
    ]
    cleaned = dict(enrichment)
    for field in string_fields:
        if field in cleaned and isinstance(cleaned[field], str):
            cleaned[field] = strip_citations(cleaned[field])
    return cleaned


def _parse_json_response(raw: str) -> dict:
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
    Called once per unique org in Pass 1.
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


def enrich_org_pass(contacts: list, db_conn_factory=None) -> dict:
    """
    Pass 1: Deduplicate organizations, research each once, auto-assign
    organization_id to all matching contacts across Railway if db_conn_factory provided.
    Returns org_cache dict keyed by lowercase org name.
    """
    import asyncio

    org_cache = {}
    seen_orgs = {}

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

        if i < total - 1:
            time.sleep(SLEEP_BETWEEN_CONTACTS)

    return org_cache


# ── TITLE-AWARE VALUE EXCHANGE REASONING ──────────────────────────────────────

def _classify_contact_type(title_role: str) -> str:
    """
    Classify a contact into a type bucket based on their title.
    Returns one of: founder, investor, operator, connector, academic, other
    """
    if not title_role:
        return "other"
    r = title_role.lower()

    if any(s in r for s in ['founder', 'co-founder', 'ceo', 'cto', 'coo', 'creator', 'building', 'started']):
        return "founder"
    if any(s in r for s in ['partner', 'principal', 'investor', 'venture', 'capital', 'fund', 'gp', 'lp', 'analyst' ]):
        # Distinguish VC partners from accelerator partners
        if any(s in r for s in ['accelerator', 'incubator', 'program', 'fellowship']):
            return "operator"
        return "investor"
    if any(s in r for s in ['professor', 'researcher', 'phd', 'faculty', 'lecturer', 'postdoc', 'academic']):
        return "academic"
    if any(s in r for s in ['director', 'manager', 'coordinator', 'officer', 'lead', 'head', 'vp', 'vice president',
                             'associate', 'fellow', 'staff', 'program', 'ecosystem', 'community', 'engagement']):
        return "operator"
    if any(s in r for s in ['connector', 'advisor', 'consultant', 'strategist', 'coach']):
        return "connector"
    return "other"


# ── PASS 2: CONTACT ENRICHMENT (NO DRAFT) ────────────────────────────────────

def enrich_and_draft(contact: dict, campaign_context: str, org_cache: dict = None) -> dict:
    """
    Pass 2: Research the individual contact and populate:
      - person_summary, research_summary, conversation_hook
      - what_i_can_offer: what Keyona can specifically bring to this person
      - what_they_offer_me: what this person brings to Keyona's network
    No email draft is generated. Drafts are on-demand via /contact/{id}/draft-outreach.
    """
    name = contact.get("full_name", "") or ""
    org = (contact.get("organization") or "").strip()
    role = (contact.get("title_role") or "").strip()
    how_we_met = contact.get("how_we_met", "") or "LinkedIn"
    existing_notes = contact.get("notes", "") or ""
    if "[Enriched" in existing_notes:
        existing_notes = existing_notes[:existing_notes.index("[Enriched")].strip()

    contact_type = _classify_contact_type(role)

    # Pull cached org data
    org_data = {}
    if org_cache and org.lower() in org_cache:
        org_data = org_cache[org.lower()]

    org_description = org_data.get("org_description", "")
    org_type = org_data.get("org_type", "")
    org_focus = org_data.get("org_focus", "")
    org_recent_activity = org_data.get("org_recent_activity", "")

    # Build type-specific value exchange guidance for the prompt
    type_guidance = {
        "founder": (
            "This person is building something. "
            "what_i_can_offer: what Keyona can introduce them to (investors, customers, talent, co-founders, advisors, press). Be specific to their stage and sector. "
            "what_they_offer_me: what their company or journey brings to Keyona's network (deal flow signal, pilot customer potential, content story, ReRev client fit, BTC portfolio candidate)."
        ),
        "investor": (
            "This person deploys capital or advises on it. "
            "what_i_can_offer: deal flow in their thesis, co-investor intros, LP candidate intros, founder referrals that fit their mandate. "
            "what_they_offer_me: capital access for founders Keyona works with, credibility signal, potential BTC LP or advisor, content collaboration."
        ),
        "operator": (
            "This person runs programs, manages ecosystems, or leads an organization. "
            "what_i_can_offer: vetted founder or talent referrals for their programs, speaker or mentor introductions, content collaboration, community connections. Be specific to what their programs need. "
            "what_they_offer_me: access to their founder or alumni network, program visibility, potential Prismm or ReRev client referrals, ecosystem intelligence."
        ),
        "academic": (
            "This person works in research or education. "
            "what_i_can_offer: practitioner connections, industry access, case study opportunities, speaking invitations, research participant referrals. "
            "what_they_offer_me: research credibility, academic network access, content depth, potential curriculum partnership for ReRev."
        ),
        "connector": (
            "This person brokers relationships professionally. "
            "what_i_can_offer: complementary network access, warm intro exchanges, collaboration on shared clients or communities. "
            "what_they_offer_me: warm path to hard-to-reach people, potential co-referral arrangement, ecosystem intelligence."
        ),
        "other": (
            "Use context clues from their title, org, and background to reason about value exchange. "
            "what_i_can_offer: specific intros, visibility, or resources Keyona can realistically provide. "
            "what_they_offer_me: what access, insight, or opportunity this person represents."
        )
    }.get(contact_type, "")

    prompt = f"""You are a relationship intelligence assistant for Keyona Meeks.

Keyona's background:
- Founder of ReRev Labs (AI education and automation consulting)
- Co-founder of Prismm (digital vault for community banks and credit unions)
- Co-manages Black Tech Capital (climate tech nano VC)
- Runs DO GOOD X accelerator
- Regularly makes introductions between founders, investors, and operators
- Based in Birmingham, Alabama

Contact to research:
- Name: {name}
- Role: {role}
- Organization: {org}
- How we met: {how_we_met}
- Contact type classification: {contact_type}
- Existing notes: {existing_notes[:200] if existing_notes else "none"}

Organization context (already researched, do not re-research):
- Description: {org_description or "not available"}
- Type: {org_type or "not available"}
- Focus: {org_focus or "not available"}
- Recent activity: {org_recent_activity or "not available"}

Value exchange guidance for this contact type:
{type_guidance}

Your tasks:
1. Search the web for public information about {name} specifically
2. Return a single JSON object with these exact keys:

{{
  "person_summary": "2-3 sentences on what is publicly known about {name} — background, notable work, current focus, any recent news",
  "person_public_profile": "LinkedIn URL or most relevant public profile URL, else empty string",
  "research_summary": "1 paragraph combining org and person context, written as a briefing Keyona would read before reaching out",
  "conversation_hook": "the single most specific and concrete thing to reference in an opening message — prefer something personal or recent",
  "what_i_can_offer": "1-2 specific sentences on what Keyona can realistically bring to this person given who they are and what they need. Not generic. Grounded in their actual role and org.",
  "what_they_offer_me": "1-2 specific sentences on what this person and their position bring to Keyona's network. What is the relationship worth and why.",
  "enrichment_status": "enriched"
}}

Return ONLY the JSON object. No markdown fences, no preamble, no citation tags."""

    try:
        client = _get_client()
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1400,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = ""
        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                result_text = block.text.strip()

        parsed = _parse_json_response(result_text)
        enrichment = clean_enrichment(parsed)

        final_enrichment = {
            "org_description": org_description,
            "org_type": org_type,
            "org_focus": org_focus,
            "org_recent_activity": org_recent_activity,
            "person_summary": enrichment.get("person_summary", ""),
            "person_public_profile": enrichment.get("person_public_profile", ""),
            "research_summary": enrichment.get("research_summary", ""),
            "conversation_hook": enrichment.get("conversation_hook", ""),
            "what_i_can_offer": enrichment.get("what_i_can_offer", ""),
            "what_they_offer_me": enrichment.get("what_they_offer_me", ""),
            "enrichment_status": enrichment.get("enrichment_status", "enriched"),
            "contact_type": contact_type,
        }

        verification_block = build_verification_block(contact, final_enrichment)

        return {
            "contact_id": contact.get("contact_id", ""),
            "full_name": name,
            "organization": org,
            "enrichment": final_enrichment,
            "verification_block": verification_block,
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
                "what_i_can_offer": "", "what_they_offer_me": "",
                "enrichment_status": f"error: {str(e)}",
                "contact_type": contact_type,
            },
            "verification_block": build_verification_block(contact, org_data),
        }


# ── ON-DEMAND DRAFT ───────────────────────────────────────────────────────────

def draft_outreach_email(contact: dict, campaign_context: str, your_goal: str = "") -> str:
    """
    Generate an on-demand outreach email draft for a specific contact.
    Reads enriched contact data already in Railway.
    Called by POST /contact/{contact_id}/draft-outreach.
    No draft is generated during enrichment — this is explicitly requested.
    """
    name = contact.get("full_name", "") or ""
    role = contact.get("title_role", "") or ""
    org = (contact.get("organization") or "").strip()
    how_we_met = contact.get("how_we_met", "") or "LinkedIn"
    what_i_can_offer = contact.get("what_i_can_offer", "") or ""
    what_they_offer_me = contact.get("what_they_offer_me", "") or ""
    conversation_hook = contact.get("conversation_hook", "") or ""
    research_summary = contact.get("research_summary", "") or ""
    person_summary = contact.get("person_summary", "") or ""
    org_description = contact.get("org_description", "") or ""

    verification_block = build_verification_block(contact, {
        "org_description": org_description,
        "person_summary": person_summary,
    })

    goal_context = f"\nKeyona's specific goal for this outreach: {your_goal}" if your_goal else ""

    prompt = f"""You are writing an outreach email for Keyona Meeks, a multi-venture founder and connector.

Who Keyona is:
- Founder of ReRev Labs (AI education and automation consulting)
- Co-founder of Prismm (digital vault for community banks and credit unions)
- Co-manages Black Tech Capital (climate tech nano VC)
- Runs DO GOOD X accelerator
- Regularly makes introductions between founders, investors, and operators
- Based in Birmingham, Alabama

Campaign context: {campaign_context}{goal_context}

Contact:
- Name: {name}
- Role: {role}
- Organization: {org}
- How we met: {how_we_met}

Research summary: {research_summary}
Conversation hook: {conversation_hook}
What Keyona can offer them: {what_i_can_offer}
What they offer Keyona's network: {what_they_offer_me}

Verification block to paste verbatim after the transition sentence:
{verification_block}

Write the email:
1. SUBJECT: line first, then blank line, then body
2. Open with 1-2 sentences using the conversation hook specifically
3. 2-3 sentences on why Keyona is reaching out, grounded in what she can offer this person specifically
4. One sentence transitioning to the verification block
5. Paste the verification block exactly as written above
6. One brief closing sentence
7. Sign: Keyona

Rules: no em-dashes, no exclamation points, no "I hope this finds you well", no mention of "Super Connector", plain text only, under 200 words not counting the verification block"""

    try:
        client = _get_client()
        response = client.messages.create(
            model=HAIKU_MODEL,
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
