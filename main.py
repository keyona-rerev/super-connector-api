import time
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os

from db import (
    init_db,
    # contacts
    store_contact, get_contact, get_all_contacts, delete_contact,
    find_similar, find_similar_by_vector,
    # initiatives
    upsert_initiative, get_initiative, get_all_initiatives, delete_initiative,
    # sub-projects
    upsert_sub_project, get_sub_projects_for_initiative, delete_sub_project,
    # stakeholders
    upsert_stakeholder, get_stakeholders_for_initiative,
    get_stakeholders_for_contact, delete_stakeholder,
    # activation angles
    upsert_activation_angle, get_all_activation_angles, delete_activation_angle,
    # action items
    upsert_action_item, get_action_items_for_initiative,
    get_open_action_items, get_action_item_by_google_task_id, delete_action_item,
)
from embedder import embed_profile
from matcher import find_matches, find_matches_by_vector
from drafter import draft_intro
from models import (
    InitiativePayload, InitiativeStatusUpdate,
    SubProjectPayload,
    StakeholderPayload, StakeholderEngagementUpdate,
    ActivationAnglePayload,
    ActionItemPayload, ActionItemStatusUpdate,
)

app = FastAPI(title="Super Connector API")

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# ── CONTACT MODELS ────────────────────────────────────────────────────────────
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

# ── OPEN ENDPOINTS ────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}

# ════════════════════════════════════════════════════════════════════════════
# CONTACTS
# ════════════════════════════════════════════════════════════════════════════

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

@app.get("/contact/{contact_id}", dependencies=[Depends(require_api_key)])
async def get_contact_by_id(contact_id: str):
    contact = await get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    # Also pull stakeholder links for cross-initiative context
    stakeholder_links = await get_stakeholders_for_contact(contact_id)
    return {"success": True, "data": contact, "initiative_links": stakeholder_links}

@app.put("/contact/{contact_id}", dependencies=[Depends(require_api_key)])
async def update_contact(contact_id: str, payload: ContactPayload):
    try:
        profile_text = _build_profile_text(payload)
        vector = embed_profile(profile_text)
        await store_contact(contact_id, payload.dict(), vector)
        return {"success": True, "contact_id": contact_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/contacts", dependencies=[Depends(require_api_key)])
async def list_contacts(limit: int = 50, offset: int = 0):
    contacts = await get_all_contacts(limit=limit, offset=offset)
    return {"success": True, "data": contacts, "count": len(contacts)}

@app.delete("/contact/{contact_id}", dependencies=[Depends(require_api_key)])
async def remove_contact(contact_id: str):
    await delete_contact(contact_id)
    return {"success": True}

@app.get("/match/{contact_id}", dependencies=[Depends(require_api_key)])
async def match_contact(contact_id: str, limit: int = 5):
    matches = await find_similar(contact_id, limit=limit)
    if matches is None:
        raise HTTPException(status_code=404, detail="Contact not found in vector DB")
    return {"contact_id": contact_id, "matches": matches}

@app.post("/search", dependencies=[Depends(require_api_key)])
async def search_contacts(request: SearchRequest):
    try:
        vector = embed_profile(request.query)
        results = await find_matches_by_vector(vector, limit=request.top_k)
        return {"query": request.query, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/draft", dependencies=[Depends(require_api_key)])
async def draft_intro_email(payload: DraftPayload):
    contact_a = await get_contact(payload.contact_a_id)
    contact_b = await get_contact(payload.contact_b_id)
    if not contact_a or not contact_b:
        raise HTTPException(status_code=404, detail="One or both contacts not found")
    result = draft_intro(contact_a, contact_b)
    return {"success": True, "draft": result}

# ════════════════════════════════════════════════════════════════════════════
# INITIATIVES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/initiatives", dependencies=[Depends(require_api_key)])
async def list_initiatives():
    data = await get_all_initiatives()
    return {"success": True, "data": data, "count": len(data)}

@app.get("/initiative/{initiative_id}", dependencies=[Depends(require_api_key)])
async def get_initiative_by_id(initiative_id: str):
    data = await get_initiative(initiative_id)
    if not data:
        raise HTTPException(status_code=404, detail="Initiative not found")
    sub_projects = await get_sub_projects_for_initiative(initiative_id)
    stakeholders = await get_stakeholders_for_initiative(initiative_id)
    action_items = await get_action_items_for_initiative(initiative_id)
    return {
        "success": True,
        "data": data,
        "sub_projects": sub_projects,
        "stakeholders": stakeholders,
        "action_items": action_items,
    }

@app.post("/initiative", dependencies=[Depends(require_api_key)])
async def create_initiative(payload: InitiativePayload):
    initiative_id = payload.initiative_id or f"INI-{int(time.time() * 1000)}"
    data = payload.dict()
    data["initiative_id"] = initiative_id
    await upsert_initiative(initiative_id, data)
    return {"success": True, "initiative_id": initiative_id}

@app.put("/initiative/{initiative_id}", dependencies=[Depends(require_api_key)])
async def update_initiative(initiative_id: str, payload: InitiativePayload):
    existing = await get_initiative(initiative_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Initiative not found")
    data = {**existing, **{k: v for k, v in payload.dict().items() if v is not None}}
    data["initiative_id"] = initiative_id
    await upsert_initiative(initiative_id, data)
    return {"success": True}

@app.patch("/initiative/{initiative_id}/status", dependencies=[Depends(require_api_key)])
async def update_initiative_status(initiative_id: str, payload: InitiativeStatusUpdate):
    existing = await get_initiative(initiative_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Initiative not found")
    existing["status"] = payload.status
    await upsert_initiative(initiative_id, existing)
    return {"success": True, "initiative_id": initiative_id, "status": payload.status}

@app.delete("/initiative/{initiative_id}", dependencies=[Depends(require_api_key)])
async def remove_initiative(initiative_id: str):
    await delete_initiative(initiative_id)
    return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# SUB-PROJECTS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/initiative/{initiative_id}/sub-projects", dependencies=[Depends(require_api_key)])
async def list_sub_projects(initiative_id: str):
    data = await get_sub_projects_for_initiative(initiative_id)
    return {"success": True, "data": data}

@app.post("/sub-project", dependencies=[Depends(require_api_key)])
async def create_sub_project(payload: SubProjectPayload):
    sub_project_id = payload.sub_project_id or f"SUB-{int(time.time() * 1000)}"
    data = payload.dict()
    data["sub_project_id"] = sub_project_id
    await upsert_sub_project(sub_project_id, payload.initiative_id, data)
    return {"success": True, "sub_project_id": sub_project_id}

@app.put("/sub-project/{sub_project_id}", dependencies=[Depends(require_api_key)])
async def update_sub_project(sub_project_id: str, payload: SubProjectPayload):
    data = payload.dict()
    data["sub_project_id"] = sub_project_id
    await upsert_sub_project(sub_project_id, payload.initiative_id, data)
    return {"success": True}

@app.delete("/sub-project/{sub_project_id}", dependencies=[Depends(require_api_key)])
async def remove_sub_project(sub_project_id: str):
    await delete_sub_project(sub_project_id)
    return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# STAKEHOLDERS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/initiative/{initiative_id}/stakeholders", dependencies=[Depends(require_api_key)])
async def list_stakeholders(initiative_id: str):
    data = await get_stakeholders_for_initiative(initiative_id)
    return {"success": True, "data": data}

@app.get("/contact/{contact_id}/initiatives", dependencies=[Depends(require_api_key)])
async def get_contact_initiatives(contact_id: str):
    """Cross-initiative surfacing — all initiatives a contact touches."""
    data = await get_stakeholders_for_contact(contact_id)
    return {"success": True, "data": data, "count": len(data)}

@app.post("/stakeholder", dependencies=[Depends(require_api_key)])
async def create_stakeholder(payload: StakeholderPayload):
    stakeholder_id = payload.stakeholder_id or f"STK-{int(time.time() * 1000)}"
    data = payload.dict()
    data["stakeholder_id"] = stakeholder_id
    await upsert_stakeholder(stakeholder_id, payload.contact_id or "", payload.initiative_id, data)
    return {"success": True, "stakeholder_id": stakeholder_id}

@app.patch("/stakeholder/{stakeholder_id}/engagement", dependencies=[Depends(require_api_key)])
async def update_stakeholder_engagement(stakeholder_id: str, payload: StakeholderEngagementUpdate):
    """Quick update for engagement status after a meeting or outreach."""
    conn_data = await get_stakeholders_for_contact("")  # placeholder — fetch by ID below
    # Re-fetch directly
    from db import _conn
    import json as _json
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT data, contact_id, initiative_id FROM stakeholders WHERE stakeholder_id = $1",
            stakeholder_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Stakeholder not found")
        data = _json.loads(row["data"])
        data["engagement_status"] = payload.engagement_status
        if payload.notes:
            data["notes"] = data.get("notes", "") + f"\n{payload.notes}"
        await upsert_stakeholder(stakeholder_id, row["contact_id"], row["initiative_id"], data)
        return {"success": True}
    finally:
        await conn.close()

@app.delete("/stakeholder/{stakeholder_id}", dependencies=[Depends(require_api_key)])
async def remove_stakeholder(stakeholder_id: str):
    await delete_stakeholder(stakeholder_id)
    return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# ACTIVATION ANGLES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/activation-angles", dependencies=[Depends(require_api_key)])
async def list_activation_angles():
    data = await get_all_activation_angles()
    return {"success": True, "data": data}

@app.post("/activation-angle", dependencies=[Depends(require_api_key)])
async def create_activation_angle(payload: ActivationAnglePayload):
    angle_id = payload.angle_id or f"ANG-{int(time.time() * 1000)}"
    data = payload.dict()
    data["angle_id"] = angle_id
    await upsert_activation_angle(angle_id, data)
    return {"success": True, "angle_id": angle_id}

@app.put("/activation-angle/{angle_id}", dependencies=[Depends(require_api_key)])
async def update_activation_angle(angle_id: str, payload: ActivationAnglePayload):
    data = payload.dict()
    data["angle_id"] = angle_id
    await upsert_activation_angle(angle_id, data)
    return {"success": True}

@app.delete("/activation-angle/{angle_id}", dependencies=[Depends(require_api_key)])
async def remove_activation_angle(angle_id: str):
    await delete_activation_angle(angle_id)
    return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# ACTION ITEMS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/action-items", dependencies=[Depends(require_api_key)])
async def list_open_action_items(due_before: Optional[str] = None):
    """Used by Phoebe for check-ins. due_before = ISO date string e.g. 2026-04-04"""
    data = await get_open_action_items(due_before=due_before)
    return {"success": True, "data": data, "count": len(data)}

@app.get("/initiative/{initiative_id}/action-items", dependencies=[Depends(require_api_key)])
async def list_action_items_for_initiative(initiative_id: str):
    data = await get_action_items_for_initiative(initiative_id)
    return {"success": True, "data": data}

@app.post("/action-item", dependencies=[Depends(require_api_key)])
async def create_action_item(payload: ActionItemPayload):
    action_id = payload.action_id or f"ACT-{int(time.time() * 1000)}"
    data = payload.dict()
    data["action_id"] = action_id
    await upsert_action_item(
        action_id,
        payload.initiative_id or "SPRINT",
        payload.stakeholder_id or "",
        data
    )
    return {"success": True, "action_id": action_id}

@app.put("/action-item/{action_id}", dependencies=[Depends(require_api_key)])
async def update_action_item(action_id: str, payload: ActionItemPayload):
    data = payload.dict()
    data["action_id"] = action_id
    await upsert_action_item(
        action_id,
        payload.initiative_id or "SPRINT",
        payload.stakeholder_id or "",
        data
    )
    return {"success": True}

@app.patch("/action-item/{action_id}/status", dependencies=[Depends(require_api_key)])
async def update_action_item_status(action_id: str, payload: ActionItemStatusUpdate):
    """Quick status update — used by Google Tasks sync and Phoebe reply processing."""
    from db import _conn
    import json as _json
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT data, initiative_id, stakeholder_id FROM action_items WHERE action_id = $1",
            action_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Action item not found")
        data = _json.loads(row["data"])
        data["status"] = payload.status
        if payload.completed_date:
            data["completed_date"] = payload.completed_date
        if payload.google_task_id:
            data["google_task_id"] = payload.google_task_id
        await upsert_action_item(action_id, row["initiative_id"], row["stakeholder_id"], data)
        return {"success": True}
    finally:
        await conn.close()

@app.get("/action-item/by-google-task/{google_task_id}", dependencies=[Depends(require_api_key)])
async def get_by_google_task_id(google_task_id: str):
    """Two-way Google Tasks sync lookup."""
    data = await get_action_item_by_google_task_id(google_task_id)
    if not data:
        raise HTTPException(status_code=404, detail="No action item found for this Google Task ID")
    return {"success": True, "data": data}

@app.delete("/action-item/{action_id}", dependencies=[Depends(require_api_key)])
async def remove_action_item(action_id: str):
    await delete_action_item(action_id)
    return {"success": True}

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
