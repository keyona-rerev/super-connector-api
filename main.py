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
    # content
    store_content, get_content, get_all_content, search_content_by_vector, delete_content,
    # follow-ups
    store_follow_up, get_follow_up, get_open_follow_ups, get_overdue_follow_ups,
    get_follow_ups_for_contact, search_follow_ups_by_vector, delete_follow_up,
    # events
    upsert_event, get_event, get_all_events, delete_event,
    upsert_event_guest, get_guests_for_event, delete_event_guest,
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
    ContentPayload, ContentStatusUpdate,
    FollowUpPayload, FollowUpStatusUpdate,
    EventPayload, EventStatusUpdate,
    EventGuestPayload, EventGuestUpdate,
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
    data = await get_action_item_by_google_task_id(google_task_id)
    if not data:
        raise HTTPException(status_code=404, detail="No action item found for this Google Task ID")
    return {"success": True, "data": data}

@app.delete("/action-item/{action_id}", dependencies=[Depends(require_api_key)])
async def remove_action_item(action_id: str):
    await delete_action_item(action_id)
    return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# CONTENT
# ════════════════════════════════════════════════════════════════════════════

@app.get("/content", dependencies=[Depends(require_api_key)])
async def list_content():
    """List all content assets."""
    data = await get_all_content()
    return {"success": True, "data": data, "count": len(data)}

@app.get("/content/{content_id}", dependencies=[Depends(require_api_key)])
async def get_content_by_id(content_id: str):
    data = await get_content(content_id)
    if not data:
        raise HTTPException(status_code=404, detail="Content not found")
    return {"success": True, "data": data}

@app.post("/content", dependencies=[Depends(require_api_key)])
async def upsert_content(payload: ContentPayload):
    try:
        content_id = payload.content_id or f"C-{int(time.time() * 1000)}"
        data = payload.dict()
        data["content_id"] = content_id
        embedding_text = _build_content_text(payload)
        vector = embed_profile(embedding_text)
        await store_content(content_id, data, vector)
        return {"success": True, "content_id": content_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/content/{content_id}", dependencies=[Depends(require_api_key)])
async def update_content(content_id: str, payload: ContentPayload):
    """Update and re-vectorize a content asset."""
    try:
        data = payload.dict()
        data["content_id"] = content_id
        embedding_text = _build_content_text(payload)
        vector = embed_profile(embedding_text)
        await store_content(content_id, data, vector)
        return {"success": True, "content_id": content_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/content/{content_id}/status", dependencies=[Depends(require_api_key)])
async def update_content_status(content_id: str, payload: ContentStatusUpdate):
    """Quick status or Prismm sync update without full re-vectorization."""
    from db import _conn
    import json as _json
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT data, embedding FROM content WHERE content_id = $1", content_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Content not found")
        data = _json.loads(row["data"])
        data["status"] = payload.status
        if payload.prismm_sync is not None:
            data["prismm_sync"] = payload.prismm_sync
        import numpy as np
        existing_vector = list(row["embedding"]) if row["embedding"] else None
        if existing_vector:
            await store_content(content_id, data, existing_vector)
        else:
            await conn.execute(
                "UPDATE content SET data = $1, updated_at = NOW() WHERE content_id = $2",
                _json.dumps(data), content_id
            )
        return {"success": True}
    finally:
        await conn.close()

@app.post("/content/search", dependencies=[Depends(require_api_key)])
async def search_content(request: SearchRequest):
    try:
        vector = embed_profile(request.query)
        results = await search_content_by_vector(vector, limit=request.top_k)
        return {"query": request.query, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/content/{content_id}", dependencies=[Depends(require_api_key)])
async def remove_content(content_id: str):
    await delete_content(content_id)
    return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# FOLLOW-UPS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/follow-ups/open", dependencies=[Depends(require_api_key)])
async def list_open_follow_ups():
    """All open follow-ups ordered by next_action_date. Used by Phoebe Monday scan."""
    data = await get_open_follow_ups()
    return {"success": True, "data": data, "count": len(data)}

@app.get("/follow-ups/overdue", dependencies=[Depends(require_api_key)])
async def list_overdue_follow_ups(as_of: Optional[str] = None):
    from datetime import date
    as_of_date = as_of or date.today().isoformat()
    data = await get_overdue_follow_ups(as_of_date)
    return {"success": True, "data": data, "count": len(data), "as_of": as_of_date}

@app.get("/contact/{contact_id}/follow-ups", dependencies=[Depends(require_api_key)])
async def list_follow_ups_for_contact(contact_id: str):
    """All follow-ups tied to a specific contact — full history."""
    data = await get_follow_ups_for_contact(contact_id)
    return {"success": True, "data": data, "count": len(data)}

@app.get("/follow-up/{follow_up_id}", dependencies=[Depends(require_api_key)])
async def get_follow_up_by_id(follow_up_id: str):
    data = await get_follow_up(follow_up_id)
    if not data:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    return {"success": True, "data": data}

@app.post("/follow-up", dependencies=[Depends(require_api_key)])
async def upsert_follow_up(payload: FollowUpPayload):
    try:
        follow_up_id = payload.follow_up_id or f"FU-{int(time.time() * 1000)}"
        data = payload.dict()
        data["follow_up_id"] = follow_up_id
        embedding_text = _build_follow_up_text(payload)
        vector = embed_profile(embedding_text)
        await store_follow_up(follow_up_id, payload.contact_id or "", data, vector)
        return {"success": True, "follow_up_id": follow_up_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/follow-up/{follow_up_id}", dependencies=[Depends(require_api_key)])
async def update_follow_up(follow_up_id: str, payload: FollowUpPayload):
    try:
        data = payload.dict()
        data["follow_up_id"] = follow_up_id
        embedding_text = _build_follow_up_text(payload)
        vector = embed_profile(embedding_text)
        await store_follow_up(follow_up_id, payload.contact_id or "", data, vector)
        return {"success": True, "follow_up_id": follow_up_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/follow-up/{follow_up_id}/status", dependencies=[Depends(require_api_key)])
async def update_follow_up_status(follow_up_id: str, payload: FollowUpStatusUpdate):
    from db import _conn
    import json as _json
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT data, contact_id, embedding FROM follow_ups WHERE follow_up_id = $1",
            follow_up_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Follow-up not found")
        data = _json.loads(row["data"])
        data["status"] = payload.status
        if payload.completed_date:
            data["completed_date"] = payload.completed_date
        import numpy as np
        existing_vector = list(row["embedding"]) if row["embedding"] else None
        if existing_vector:
            await store_follow_up(follow_up_id, row["contact_id"], data, existing_vector)
        else:
            await conn.execute(
                "UPDATE follow_ups SET data = $1, updated_at = NOW() WHERE follow_up_id = $2",
                _json.dumps(data), follow_up_id
            )
        return {"success": True, "follow_up_id": follow_up_id, "status": payload.status}
    finally:
        await conn.close()

@app.post("/follow-ups/search", dependencies=[Depends(require_api_key)])
async def search_follow_ups(request: SearchRequest):
    try:
        vector = embed_profile(request.query)
        results = await search_follow_ups_by_vector(vector, limit=request.top_k)
        return {"query": request.query, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/follow-up/{follow_up_id}", dependencies=[Depends(require_api_key)])
async def remove_follow_up(follow_up_id: str):
    await delete_follow_up(follow_up_id)
    return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# EVENTS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/events", dependencies=[Depends(require_api_key)])
async def list_events(type: Optional[str] = None, venture: Optional[str] = None):
    """
    List all events. Optional filters:
      ?type=Hosting   — Hosting / Attending / Workshop
      ?venture=BTC    — any venture name
    """
    data = await get_all_events(event_type=type, venture=venture)
    return {"success": True, "data": data, "count": len(data)}

@app.get("/event/{event_id}", dependencies=[Depends(require_api_key)])
async def get_event_by_id(event_id: str):
    """Fetch event + full guest list."""
    data = await get_event(event_id)
    if not data:
        raise HTTPException(status_code=404, detail="Event not found")
    guests = await get_guests_for_event(event_id)
    confirmed = sum(1 for g in guests if g.get("guest_status") == "Confirmed")
    attended = sum(1 for g in guests if g.get("guest_status") == "Attended")
    return {
        "success": True,
        "data": data,
        "guests": guests,
        "guest_summary": {
            "total": len(guests),
            "confirmed": confirmed,
            "attended": attended,
        },
    }

@app.post("/event", dependencies=[Depends(require_api_key)])
async def create_event(payload: EventPayload):
    event_id = payload.event_id or f"EVT-{int(time.time() * 1000)}"
    data = payload.dict()
    data["event_id"] = event_id
    await upsert_event(event_id, data)
    return {"success": True, "event_id": event_id}

@app.put("/event/{event_id}", dependencies=[Depends(require_api_key)])
async def update_event(event_id: str, payload: EventPayload):
    existing = await get_event(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
    data = {**existing, **{k: v for k, v in payload.dict().items() if v is not None}}
    data["event_id"] = event_id
    await upsert_event(event_id, data)
    return {"success": True}

@app.patch("/event/{event_id}/status", dependencies=[Depends(require_api_key)])
async def update_event_status(event_id: str, payload: EventStatusUpdate):
    existing = await get_event(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
    existing["status"] = payload.status
    await upsert_event(event_id, existing)
    return {"success": True, "event_id": event_id, "status": payload.status}

@app.delete("/event/{event_id}", dependencies=[Depends(require_api_key)])
async def remove_event(event_id: str):
    await delete_event(event_id)
    return {"success": True}

@app.get("/event/{event_id}/guests", dependencies=[Depends(require_api_key)])
async def list_event_guests(event_id: str):
    guests = await get_guests_for_event(event_id)
    return {"success": True, "data": guests, "count": len(guests)}

@app.post("/event-guest", dependencies=[Depends(require_api_key)])
async def add_event_guest(payload: EventGuestPayload):
    guest_id = payload.guest_id or f"EG-{int(time.time() * 1000)}"
    data = payload.dict()
    data["guest_id"] = guest_id
    await upsert_event_guest(guest_id, payload.event_id, payload.contact_id or "", data)
    return {"success": True, "guest_id": guest_id}

@app.patch("/event-guest/{guest_id}", dependencies=[Depends(require_api_key)])
async def update_event_guest(guest_id: str, payload: EventGuestUpdate):
    """Update guest role, status, or notes. Omitted fields are preserved."""
    from db import _conn
    import json as _json
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT event_id, contact_id, data FROM event_guests WHERE guest_id = $1",
            guest_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Event guest not found")
        data = _json.loads(row["data"])
        if payload.role is not None:
            data["role"] = payload.role
        if payload.guest_status is not None:
            data["guest_status"] = payload.guest_status
        if payload.notes is not None:
            data["notes"] = payload.notes
        await upsert_event_guest(guest_id, row["event_id"], row["contact_id"], data)
        return {"success": True}
    finally:
        await conn.close()

@app.delete("/event-guest/{guest_id}", dependencies=[Depends(require_api_key)])
async def remove_event_guest(guest_id: str):
    await delete_event_guest(guest_id)
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

def _build_content_text(content: ContentPayload) -> str:
    parts = [
        f"Content: {content.content_name}",
        f"Type: {content.content_type}" if content.content_type else "",
        f"Venture: {content.venture}" if content.venture else "",
        f"Initiatives: {content.initiative_tags}" if content.initiative_tags else "",
        f"Purpose: {content.activation_angle}" if content.activation_angle else "",
        f"Notes: {content.notes}" if content.notes else "",
    ]
    return " | ".join(p for p in parts if p)

def _build_follow_up_text(follow_up: FollowUpPayload) -> str:
    parts = [
        f"Follow-up with: {follow_up.contact_name}",
        f"Meeting: {follow_up.meeting_name}" if follow_up.meeting_name else "",
        f"Action needed: {follow_up.next_action}" if follow_up.next_action else "",
        f"Venture: {follow_up.venture}" if follow_up.venture else "",
        f"Notes: {follow_up.notes}" if follow_up.notes else "",
    ]
    return " | ".join(p for p in parts if p)
