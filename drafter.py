import os
import anthropic

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client

def draft_intro(contact_a: dict, contact_b: dict) -> dict:
    """
    Given two contact profiles, use Claude to draft a warm intro email
    that Keyona can send between them.
    """
    client = _get_client()

    def fmt(c: dict) -> str:
        lines = [
            f"Name: {c.get('full_name', '')}",
            f"Role: {c.get('title_role', '')}",
            f"Organization: {c.get('organization', '')}",
            f"How Keyona knows them: {c.get('how_we_met', '')}",
            f"Venture context: {c.get('venture', '')}",
            f"What they're building: {c.get('what_building', '')}",
            f"What they need: {c.get('what_need', '')}",
            f"What they offer: {c.get('what_offer', '')}",
            f"Notes: {c.get('notes', '')}",
        ]
        return "\n".join(l for l in lines if not l.endswith(": "))

    prompt = f"""You are a relationship intelligence assistant for Keyona Meeks.
Keyona is a founder running ReRev Labs (AI education and operations consulting), 
Black Tech Capital (climate tech VC), and Prismm (digital vault platform for financial institutions).
She is a connector and wants to proactively introduce people in her network who would benefit from knowing each other.

Draft a short, warm intro email Keyona can send to make an introduction between these two people.

Person A:
{fmt(contact_a)}

Person B:
{fmt(contact_b)}

Write a subject line and a short email body (3-4 sentences max).
- First sentence: why Keyona is making the intro
- One sentence each on what makes each person interesting to the other
- A brief call to action

Be specific, warm, and direct. Do not use filler phrases like "I think you two would really hit it off."
Return your response as JSON with keys: subject, body"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    import json
    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        # Fallback: return raw text if JSON parsing fails
        return {"subject": "Introduction", "body": raw}
