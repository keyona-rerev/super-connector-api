from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os

from db import init_db, store_contact, get_contact, get_all_contacts, delete_contact
from embedder import embed_profile
from matcher import find_matches, find_matches_by_vector
from drafter import draft_intro

app = FastAPI(title="Super Connector API")

# ── CORS ──────────────────────────────────────────────────────────────────────
# Allows the GitHub Pages web app and GAS to call this API from a browser/server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten to your GitHub Pages URL after launch
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── AUTH ──────────────────────────────────────────────────────────────────────
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

def require_api_key(key: str = Security(api_key_header)):
    expected = os.environ.get("SC_API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="API key not configured on server")
    if key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key

# ── STARTUP ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    await init_db()

# ── MODELS ────────────────────────────────────────────────────────────────────
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

# ── OPEN ENDPOINTS (no auth) ──────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}

# ── PROTECTED ENDPOINTS ───────────────────────────────────────────────────────
@app.post("/contact", dependencies=[Depends(require_api_key)])
async def upsert_contact(payload: ContactPayload):
    try:
        profile_text = _build_profile_text(payload)
        vector = embed_profile(profile_text)
        await store_contact(payload.contact_id, payload.dict(), vector)
        return {"success": True, "contact_id": payload.contact_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/contact/bulk", dependencies=[Depends(require_api_key)])
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

@app.put("/contact/{contact_id}", dependencies=[Depends(require_api_key)])
async def update_contact(contact_id: str, payload: ContactPayload):
    try:
        profile_text = _build_profile_text(payload)
        vector = embed_profile(profile_text)
        await store_contact(contact_id, payload.dict(), vector)
        return {"success": True, "contact_id": contact_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/contact/{contact_id}", dependencies=[Depends(require_api_key)])
async def get_contact_by_id(contact_id: str):
    try:
        contact = await get_contact(contact_id)
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        return {"success": True, "data": contact}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/contacts", dependencies=[Depends(require_api_key)])
async def list_contacts(limit: int = 50, offset: int = 0):
    try:
        contacts = await get_all_contacts(limit=limit, offset=offset)
        return {"success": True, "data": contacts, "count": len(contacts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/contact/{contact_id}", dependencies=[Depends(require_api_key)])
async def remove_contact(contact_id: str):
    try:
        await delete_contact(contact_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/match/{contact_id}", dependencies=[Depends(require_api_key)])
async def match_contact(contact_id: str, limit: int = 5):
    try:
        matches = await find_matches(contact_id, limit=limit)
        if matches is None:
            raise HTTPException(status_code=404, detail="Contact not found in vector DB")
        return {"contact_id": contact_id, "matches": matches}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/draft", dependencies=[Depends(require_api_key)])
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

@app.post("/search", dependencies=[Depends(require_api_key)])
async def search_contacts(request: SearchRequest):
    try:
        vector = embed_profile(request.query)
        results = await find_matches_by_vector(vector, limit=request.top_k)
        return {"query": request.query, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── HELPERS ───────────────────────────────────────────────────────────────────
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
