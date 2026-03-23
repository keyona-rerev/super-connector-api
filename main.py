from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

from db import init_db, store_contact, get_contact, get_all_contacts, delete_contact
from embedder import embed_profile
from matcher import find_matches
from drafter import draft_intro

app = FastAPI(title="Super Connector API")

@app.on_event("startup")
async def startup():
    init_db()

# ── Models ──────────────────────────────────────────────────────────────────

class ContactPayload(BaseModel):
    contact_id: str
    full_name: str
    title_role: Optional[str] = ""
    organization: Optional[str] = ""
    how_we_met: Optional[str] = ""
    venture: Optional[str] = ""
    what_building: Optional[str] = ""
    what_need: Optional[str] = ""
    what_offer: Optional[str] = ""
    relationship_health: Optional[str] = ""
    activation_potential: Optional[str] = ""
    notes: Optional[str] = ""

class BulkPayload(BaseModel):
    contacts: list[ContactPayload]

class DraftPayload(BaseModel):
    contact_a_id: str
    contact_b_id: str

# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/contact")
def upsert_contact(payload: ContactPayload):
    """Embed a single contact and store/update in pgvector."""
    try:
        profile_text = _build_profile_text(payload)
        vector = embed_profile(profile_text)
        store_contact(payload.contact_id, payload.dict(), vector)
        return {"success": True, "contact_id": payload.contact_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/contact/bulk")
def bulk_upsert(payload: BulkPayload):
    """Embed and store all contacts — used for retroactive vectorization."""
    results = {"success": 0, "skipped": 0, "errors": []}
    for contact in payload.contacts:
        try:
            profile_text = _build_profile_text(contact)
            vector = embed_profile(profile_text)
            store_contact(contact.contact_id, contact.dict(), vector)
            results["success"] += 1
        except Exception as e:
            results["errors"].append({"contact_id": contact.contact_id, "error": str(e)})
            results["skipped"] += 1
    return results

@app.put("/contact/{contact_id}")
def update_contact(contact_id: str, payload: ContactPayload):
    """Re-embed a contact after profile update."""
    try:
        profile_text = _build_profile_text(payload)
        vector = embed_profile(profile_text)
        store_contact(contact_id, payload.dict(), vector)
        return {"success": True, "contact_id": contact_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/match/{contact_id}")
def match_contact(contact_id: str, limit: int = 5):
    """Find top N semantically similar contacts."""
    try:
        matches = find_matches(contact_id, limit=limit)
        if matches is None:
            raise HTTPException(status_code=404, detail="Contact not found in vector DB")
        return {"contact_id": contact_id, "matches": matches}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/draft")
def draft_intro_email(payload: DraftPayload):
    """Given two contact IDs, retrieve their profiles and draft an intro email."""
    try:
        contact_a = get_contact(payload.contact_a_id)
        contact_b = get_contact(payload.contact_b_id)
        if not contact_a or not contact_b:
            raise HTTPException(status_code=404, detail="One or both contacts not found")
        result = draft_intro(contact_a, contact_b)
        return {"success": True, "draft": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_profile_text(contact: ContactPayload) -> str:
    """Build a rich text string from a contact profile for embedding."""
    parts = [
        f"Name: {contact.full_name}",
        f"Role: {contact.title_role}" if contact.title_role else "",
        f"Organization: {contact.organization}" if contact.organization else "",
        f"Venture context: {contact.venture}" if contact.venture else "",
        f"How we met: {contact.how_we_met}" if contact.how_we_met else "",
        f"What they're building: {contact.what_building}" if contact.what_building else "",
        f"What they need: {contact.what_need}" if contact.what_need else "",
        f"What they offer: {contact.what_offer}" if contact.what_offer else "",
        f"Notes: {contact.notes}" if contact.notes else "",
    ]
    return " | ".join(p for p in parts if p)
