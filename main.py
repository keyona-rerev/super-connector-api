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
    await init_db()

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

class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 10

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/contact")
async def upsert_contact(payload: ContactPayload):
    try:
        profile_text = _build_profile_text(payload)
        vector = embed_profile(profile_text)
        await store_contact(payload.contact_id, payload.dict(), vector)
        return {"success": True, "contact_id": payload.contact_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/contact/bulk")
async def bulk_upsert(payload: BulkPayload):
    results = {"success": 0, "skipped": 0, "errors": []}
    for contact in payload.contacts:
        try:
            profile_text = _build_profile_text(contact)
            vector = embed_profile(profile_text)
            await store_contact(contact.contact_id, contact.dict(), vector)
            results["success"] += 1
        except Exception as e:
            results["errors"].append({"contact_id": contact.contact_id, "error": str(e)})
            results["skipped"] += 1
    return results

@app.put("/contact/{contact_id}")
async def update_contact(contact_id: str, payload: ContactPayload):
    try:
        profile_text = _build_profile_text(payload)
        vector = embed_profile(profile_text)
        await store_contact(contact_id, payload.dict(), vector)
        return {"success": True, "contact_id": contact_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/match/{contact_id}")
async def match_contact(contact_id: str, limit: int = 5):
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
async def draft_intro_email(payload: DraftPayload):
    try:
        contact_a = await get_contact(payload.contact_a_id)
        contact_b = await get_contact(payload.contact_b_id)
        if not contact_a or not contact_b:
            raise HTTPException(status_code=404, detail="One or both contacts not found")
        result = draft_intro(contact_a, contact_b)
        return {"success": True, "draft": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
async def search_contacts(request: SearchRequest):
    try:
        vector = embed_profile(request.query)
        matches = find_matches_by_vector(vector, limit=request.top_k)
        return {"query": request.query, "results": matches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _build_profile_text(contact: ContactPayload) -> str:
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
