import time
from fastapi import FastAPI, HTTPException, Security, Depends, BackgroundTasks
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any, Dict
import os
import asyncio

from db import (
    init_db,
    store_contact, get_contact, get_all_contacts, count_contacts, delete_contact,
    find_similar, find_similar_by_vector, text_search_contacts,
    upsert_organization, get_organization, get_all_organizations, delete_organization,
    find_organization_by_name, find_organizations_by_name_fuzzy,
    get_contacts_for_org, preview_org_link, commit_org_link,
    upsert_initiative, get_initiative, get_all_initiatives, delete_initiative,
    upsert_sub_project, get_sub_projects_for_initiative, delete_sub_project,
    upsert_stakeholder, get_stakeholders_for_initiative,
    get_stakeholders_for_contact, delete_stakeholder,
    upsert_activation_angle, get_all_activation_angles, delete_activation_angle,
    upsert_action_item, get_action_items_for_initiative,
    get_open_action_items, get_action_item_by_google_task_id, delete_action_item,
    store_content, get_content, get_all_content, search_content_by_vector, delete_content,
    store_follow_up, get_follow_up, get_open_follow_ups, get_overdue_follow_ups,
    get_follow_ups_for_contact, search_follow_ups_by_vector, delete_follow_up,
    upsert_event, get_event, get_all_events, delete_event,
    upsert_event_guest, get_guests_for_event, delete_event_guest,
    upsert_bucket, get_all_buckets, get_bucket, delete_bucket,
    add_contact_to_bucket, remove_contact_from_bucket,
    get_buckets_for_contact, get_contacts_in_bucket, get_buckets_for_initiative,
    brain_dump_insert,
    add_contact_note, get_contact_notes, delete_contact_note,
)
from embedder import embed_profile, embed_query
from matcher import find_matches, find_matches_by_vector
from drafter import draft_intro
from enricher import enrich_and_draft, enrich_org_pass, draft_outreach_email
from models import (
    OrganizationPayload,
    InitiativePayload, InitiativeStatusUpdate,
    SubProjectPayload,
    StakeholderPayload, StakeholderEngagementUpdate,
    ActivationAnglePayload,
    ActionItemPayload, ActionItemStatusUpdate,
    ContentPayload, ContentStatusUpdate,
    FollowUpPayload, FollowUpStatusUpdate,
    EventPayload, EventStatusUpdate,
    EventGuestPayload, EventGuestUpdate,
    CandidacyUpdate, DraftOutreachPayload, InitiativeLinkPayload, CANDIDACY_STATUSES,
)

app = FastAPI(title="Super Connector API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

def require_api_key(key: str = Security(api_key_header)):
    expected = os.environ.get("SC_API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="API key not configured on server")
    if key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key

@app.on_event("startup")
async def startup():
    await init_db()

# ════════════════════════════════════════════════════════════════════════════
# BACKGROUND JOB STATE (in-memory, single-process Railway)
# ════════════════════════════════════════════════════════════════════════════

# Haiku pricing as of 2025: $0.80/M input tokens, $4.00/M output tokens
HAIKU_INPUT_COST_PER_TOKEN = 0.80 / 1_000_000
HAIKU_OUTPUT_COST_PER_TOKEN = 4.00 / 1_000_000
COST_WARNING_THRESHOLD = 5.00  # dollars

_enrich_jobs: Dict[str, dict] = {}


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * HAIKU_INPUT_COST_PER_TOKEN) + (output_tokens * HAIKU_OUTPUT_COST_PER_TOKEN)


async def _run_enrich_all_job(job_id: str, bucket_id: str, campaign_context: str):
    """
    Background task: enrich every unenriched contact in a bucket one at a time.
    Tracks estimated cost. Halts and flags if spend exceeds COST_WARNING_THRESHOLD.
    Skips contacts that already have what_i_can_offer populated.
    """
    job = _enrich_jobs[job_id]
    job["status"] = "running"

    try:
        all_contacts = await get_contacts_in_bucket(bucket_id)
        to_enrich = [c for c in all_contacts if not (c.get("what_i_can_offer") or "").strip()]

        job["total"] = len(all_contacts)
        job["to_enrich"] = len(to_enrich)
        job["processed"] = 0
        job["skipped_already_done"] = len(all_contacts) - len(to_enrich)
        job["succeeded"] = 0
        job["failed"] = []
        job["estimated_cost_usd"] = 0.0
        job["cost_halted"] = False

        loop = asyncio.get_event_loop()

        for i, contact in enumerate(to_enrich):
            # Check cost before each contact
            if job["estimated_cost_usd"] >= COST_WARNING_THRESHOLD:
                job["cost_halted"] = True
                job["status"] = "halted_cost_limit"
                job["message"] = (
                    f"Halted after {job['succeeded']} contacts. "
                    f"Estimated spend reached ${job['estimated_cost_usd']:.4f}, "
                    f"which hit the ${COST_WARNING_THRESHOLD:.2f} warning threshold. "
                    f"Call /bucket/{bucket_id}/enrich-status to review, then restart if needed."
                )
                return

            contact_id = contact.get("contact_id", "")
            name = contact.get("full_name", "Unknown")
            job["current_contact"] = name

            try:
                # Org pass for just this one contact
                org_cache = await loop.run_in_executor(None, enrich_org_pass, [contact])

                # Contact enrichment pass
                result = await loop.run_in_executor(
                    None, enrich_and_draft, contact, campaign_context, org_cache
                )

                enrichment = result.get("enrichment", {})
                status = enrichment.get("enrichment_status", "")

                # Estimate tokens: org prompt ~800 in/200 out, contact prompt ~1200 in/400 out
                job["estimated_cost_usd"] += _estimate_cost(2000, 600)

                if status == "enriched":
                    existing = await get_contact(contact_id)
                    if existing:
                        if enrichment.get("what_i_can_offer"):
                            existing["what_i_can_offer"] = enrichment["what_i_can_offer"]
                        if enrichment.get("what_they_offer_me"):
                            existing["what_they_offer_me"] = enrichment["what_they_offer_me"]
                        if enrichment.get("contact_type"):
                            existing["contact_type"] = enrichment["contact_type"]

                        org_ctx = enrichment.get("org_description", "")
                        person_ctx = enrichment.get("person_summary", "")
                        recent = enrichment.get("org_recent_activity", "")
                        parts = []
                        if org_ctx: parts.append(f"Org: {org_ctx}")
                        if person_ctx: parts.append(f"Person: {person_ctx}")
                        if recent: parts.append(f"Recent: {recent}")
                        if parts:
                            enrich_note = f"\n[Enriched {time.strftime('%Y-%m-%d')}] " + " | ".join(parts)
                            existing_notes = existing.get("notes", "") or ""
                            if "[Enriched" not in existing_notes:
                                existing["notes"] = (existing_notes + enrich_note).strip()

                        profile_text = " | ".join(filter(None, [
                            f"Name: {existing.get('full_name', '')}",
                            f"Role: {existing.get('title_role', '')}",
                            f"Org: {existing.get('organization', '')}",
                            f"What I can offer: {existing.get('what_i_can_offer', '')}",
                            f"What they offer me: {existing.get('what_they_offer_me', '')}",
                            f"Notes: {existing.get('notes', '')}",
                        ]))
                        await store_contact(contact_id, existing, embed_profile(profile_text))

                    job["succeeded"] += 1
                else:
                    job["failed"].append({"id": contact_id, "name": name, "status": status})

            except Exception as e:
                job["failed"].append({"id": contact_id, "name": name, "error": str(e)})

            job["processed"] += 1

            # 3s pause between contacts — enough breathing room without being slow
            if i < len(to_enrich) - 1:
                await asyncio.sleep(3)

        job["status"] = "complete"
        job["current_contact"] = None
        job["message"] = (
            f"Done. {job['succeeded']} enriched, {len(job['failed'])} failed, "
            f"{job['skipped_already_done']} already had data. "
            f"Estimated cost: ${job['estimated_cost_usd']:.4f}"
        )

    except Exception as e:
        job["status"] = "error"
        job["message"] = str(e)


class BucketEnrichAllPayload(BaseModel):
    campaign_context: str


class ContactPayload(BaseModel):
    contact_id: str
    full_name: str
    title_role: Optional[str] = ""
    organization: Optional[str] = ""
    organization_id: Optional[str] = ""
    organization_ids: Optional[List[str]] = []
    how_we_met: Optional[str] = ""
    venture: Optional[str] = ""
    what_building: Optional[str] = ""
    what_need: Optional[str] = ""
    what_offer: Optional[str] = ""
    what_i_can_offer: Optional[str] = ""
    what_they_offer_me: Optional[str] = ""
    contact_type: Optional[str] = ""
    outreach_candidacy: Optional[str] = ""
    relationship_health: Optional[str] = ""
    activation_potential: Optional[str] = ""
    source: Optional[str] = ""
    imported_via: Optional[str] = ""
    active_advocacy: Optional[bool] = False
    notes: Optional[str] = ""

class BulkPayload(BaseModel):
    contacts: list[ContactPayload]

class DraftPayload(BaseModel):
    contact_a_id: str
    contact_b_id: str

class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 10

class BucketPayload(BaseModel):
    bucket_id: Optional[str] = None
    name: str
    description: Optional[str] = ""
    color: Optional[str] = ""
    initiative_id: Optional[str] = ""

class BucketMemberPayload(BaseModel):
    contact_id: str

class BucketFromSearchPayload(BaseModel):
    description: str
    bucket_name: str
    bucket_color: Optional[str] = "#6BC47F"
    initiative_id: Optional[str] = ""
    top_k: Optional[int] = 20
    auto_commit: Optional[bool] = False

class BucketEnrichPayload(BaseModel):
    campaign_context: str
    batch_size: Optional[int] = 1
    offset: Optional[int] = 0
    write_back: Optional[bool] = True

class BrainDumpSubProject(BaseModel):
    sub_project_name: str
    description: Optional[str] = ""
    status: Optional[str] = "Not Started"
    priority: Optional[str] = "Medium"
    notes: Optional[str] = ""

class BrainDumpInitiative(BaseModel):
    initiative_name: str
    venture: Optional[str] = ""
    goal: Optional[str] = ""
    status: Optional[str] = "Brain Dump"
    priority: Optional[str] = "Medium"
    notes: Optional[str] = ""
    phoebe_cadence: Optional[str] = "Weekly"
    brain_dump: Optional[str] = ""
    sub_projects: Optional[List[BrainDumpSubProject]] = []

class BrainDumpContact(BaseModel):
    full_name: str
    title_role: Optional[str] = ""
    organization: Optional[str] = ""
    how_we_met: Optional[str] = ""
    venture: Optional[str] = ""
    relationship_health: Optional[str] = "Lukewarm"
    activation_potential: Optional[str] = "Medium"
    imported_via: Optional[str] = ""
    active_advocacy: Optional[bool] = False
    notes: Optional[str] = ""

class BrainDumpActionItem(BaseModel):
    description: str
    initiative_id: Optional[str] = "SPRINT"
    action_type: Optional[str] = "Research"
    priority: Optional[str] = "Medium"
    due_date: Optional[str] = None
    status: Optional[str] = "Open"
    source: Optional[str] = "Brain Dump"

class BrainDumpPayload(BaseModel):
    initiatives: Optional[List[BrainDumpInitiative]] = []
    contacts: Optional[List[BrainDumpContact]] = []
    action_items: Optional[List[BrainDumpActionItem]] = []

class ContactNotePayload(BaseModel):
    body: str
    source: Optional[str] = "manual"
    note_date: Optional[str] = None

def _build_profile_text(contact: ContactPayload) -> str:
    parts = [
        f"Name: {contact.full_name}",
        f"Role: {contact.title_role}" if contact.title_role else "",
        f"Organization: {contact.organization}" if contact.organization else "",
        f"Venture context: {contact.venture}" if contact.venture else "",
        f"How we met: {contact.how_we_met}" if contact.how_we_met else "",
        f"What they're building: {contact.what_building}" if contact.what_building else "",
        f"What they need: {contact.what_need}" if contact.what_need else "",
        f"What I can offer them: {contact.what_i_can_offer}" if contact.what_i_can_offer else "",
        f"What they offer me: {contact.what_they_offer_me}" if contact.what_they_offer_me else "",
        f"Met at: {contact.source}" if contact.source else "",
        f"Notes: {contact.notes}" if contact.notes else "",
    ]
    return " | ".join(p for p in parts if p)

def _build_content_text(content: ContentPayload) -> str:
    parts = [f"Content: {content.content_name}", f"Type: {content.content_type}" if content.content_type else "", f"Venture: {content.venture}" if content.venture else "", f"Initiatives: {content.initiative_tags}" if content.initiative_tags else "", f"Purpose: {content.activation_angle}" if content.activation_angle else "", f"Notes: {content.notes}" if content.notes else ""]
    return " | ".join(p for p in parts if p)

def _build_follow_up_text(follow_up: FollowUpPayload) -> str:
    parts = [f"Follow-up with: {follow_up.contact_name}", f"Meeting: {follow_up.meeting_name}" if follow_up.meeting_name else "", f"Action needed: {follow_up.next_action}" if follow_up.next_action else "", f"Venture: {follow_up.venture}" if follow_up.venture else "", f"Notes: {follow_up.notes}" if follow_up.notes else ""]
    return " | ".join(p for p in parts if p)

@app.get("/health")
def health():
    return {"status": "ok"}

# ════════════════════════════════════════════════════════════════════════════
# CONTACT NOTES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/contact/{contact_id}/notes", dependencies=[Depends(require_api_key)])
async def list_contact_notes(contact_id: str, limit: int = 50):
    data = await get_contact_notes(contact_id, limit=limit)
    return {"success": True, "data": data, "count": len(data)}

@app.post("/contact/{contact_id}/notes", dependencies=[Depends(require_api_key)])
async def add_note_to_contact(contact_id: str, payload: ContactNotePayload):
    note_id = f"NOTE-{int(time.time() * 1000)}"
    await add_contact_note(note_id=note_id, contact_id=contact_id, body=payload.body.strip(), source=payload.source or "manual", note_date=payload.note_date or None)
    return {"success": True, "note_id": note_id}

@app.delete("/contact/{contact_id}/notes/{note_id}", dependencies=[Depends(require_api_key)])
async def remove_contact_note(contact_id: str, note_id: str):
    await delete_contact_note(note_id)
    return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# ORGANIZATIONS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/organizations", dependencies=[Depends(require_api_key)])
async def list_organizations():
    data = await get_all_organizations()
    return {"success": True, "data": data, "count": len(data)}

@app.get("/organization/{org_id}", dependencies=[Depends(require_api_key)])
async def get_org_by_id(org_id: str):
    data = await get_organization(org_id)
    if not data: raise HTTPException(status_code=404, detail="Organization not found")
    contacts = await get_contacts_for_org(org_id)
    return {"success": True, "data": data, "contacts": contacts, "contact_count": len(contacts)}

@app.post("/organization", dependencies=[Depends(require_api_key)])
async def create_organization(payload: OrganizationPayload):
    org_id = payload.org_id or f"ORG-{int(time.time() * 1000)}"; data = payload.dict(); data["org_id"] = org_id
    org_text = " | ".join(filter(None, [f"Org: {payload.name}", f"Type: {payload.org_type}" if payload.org_type else "", f"Focus: {payload.org_focus}" if payload.org_focus else "", f"Description: {payload.description}" if payload.description else ""]))
    vector = embed_profile(org_text) if org_text.strip() else None
    await upsert_organization(org_id, data, vector)
    return {"success": True, "org_id": org_id}

@app.put("/organization/{org_id}", dependencies=[Depends(require_api_key)])
async def update_organization(org_id: str, payload: OrganizationPayload):
    existing = await get_organization(org_id)
    if not existing: raise HTTPException(status_code=404, detail="Organization not found")
    data = {**existing, **{k: v for k, v in payload.dict().items() if v is not None}}; data["org_id"] = org_id
    org_text = " | ".join(filter(None, [f"Org: {data.get('name','')}", f"Type: {data.get('org_type','')}" if data.get("org_type") else "", f"Description: {data.get('description','')}" if data.get("description") else ""]))
    await upsert_organization(org_id, data, embed_profile(org_text) if org_text.strip() else None)
    return {"success": True}

@app.delete("/organization/{org_id}", dependencies=[Depends(require_api_key)])
async def remove_organization(org_id: str):
    await delete_organization(org_id); return {"success": True}

@app.post("/organization/{org_id}/research", dependencies=[Depends(require_api_key)])
async def research_organization(org_id: str):
    existing = await get_organization(org_id)
    if not existing: raise HTTPException(status_code=404, detail="Organization not found")
    org_name = existing.get("name", "")
    if not org_name: raise HTTPException(status_code=400, detail="Organization has no name to research")
    from enricher import research_org
    enrichment = research_org(org_name)
    if enrichment.get("enrichment_status") == "enriched":
        existing["org_type"] = enrichment.get("org_type") or existing.get("org_type", "")
        existing["org_focus"] = enrichment.get("org_focus") or existing.get("org_focus", "")
        existing["description"] = enrichment.get("org_description") or existing.get("description", "")
        existing["recent_activity"] = enrichment.get("org_recent_activity") or existing.get("recent_activity", "")
        existing["conversation_hook"] = enrichment.get("conversation_hook") or existing.get("conversation_hook", "")
        existing["last_enriched"] = time.strftime("%Y-%m-%d")
        org_text = " | ".join(filter(None, [f"Org: {org_name}", f"Type: {existing.get('org_type','')}", f"Description: {existing.get('description','')}"]))
        await upsert_organization(org_id, existing, embed_profile(org_text) if org_text.strip() else None)
    return {"success": True, "org_id": org_id, "enrichment_status": enrichment.get("enrichment_status"), "data": existing}

@app.get("/organizations/link-preview", dependencies=[Depends(require_api_key)])
async def org_link_preview(org_name: str):
    preview = await preview_org_link(org_name)
    return {"success": True, **preview}

@app.post("/organizations/link-contacts", dependencies=[Depends(require_api_key)])
async def link_contacts_to_org(org_id: str, org_name: str):
    org = await get_organization(org_id)
    if not org: raise HTTPException(status_code=404, detail="Organization not found")
    updated = await commit_org_link(org_id, org_name)
    return {"success": True, "org_id": org_id, "org_name": org_name, "contacts_linked": updated}

# ════════════════════════════════════════════════════════════════════════════
# BRAIN DUMP
# ════════════════════════════════════════════════════════════════════════════

@app.post("/brain-dump", dependencies=[Depends(require_api_key)])
async def brain_dump(payload: BrainDumpPayload):
    ts = lambda: int(time.time() * 1000)
    flat_initiatives, flat_sub_projects, flat_contacts, flat_action_items = [], [], [], []
    for ini in (payload.initiatives or []):
        ini_id = f"INI-{ts()}"; ini_data = ini.dict(); subs = ini_data.pop("sub_projects", []) or []; ini_data["initiative_id"] = ini_id; flat_initiatives.append(ini_data)
        for sub in subs: sub["sub_project_id"] = f"SUB-{ts()}"; sub["initiative_id"] = ini_id; flat_sub_projects.append(sub)
    for contact in (payload.contacts or []):
        c_data = contact.dict(); c_data["contact_id"] = f"C{ts()}"; flat_contacts.append(c_data)
    for item in (payload.action_items or []):
        a_data = item.dict(); a_data["action_id"] = f"ACT-{ts()}"; flat_action_items.append(a_data)
    results = await brain_dump_insert(flat_initiatives, flat_sub_projects, flat_contacts, flat_action_items)
    for c in flat_contacts:
        try:
            profile_text = " | ".join(filter(None, [f"Name: {c.get('full_name','')}", f"Role: {c.get('title_role','')}", f"Org: {c.get('organization','')}", f"Notes: {c.get('notes','')}"]))
            await store_contact(c["contact_id"], c, embed_profile(profile_text))
        except Exception: pass
    total_errors = sum(len(v["errors"]) for v in results.values())
    return {"success": total_errors == 0, "summary": {k: v["ok"] for k, v in results.items()}, "errors": results if total_errors > 0 else None}

# ════════════════════════════════════════════════════════════════════════════
# CONTACTS
# ════════════════════════════════════════════════════════════════════════════

@app.post("/contact", dependencies=[Depends(require_api_key)])
async def upsert_contact(payload: ContactPayload):
    try:
        await store_contact(payload.contact_id, payload.dict(), embed_profile(_build_profile_text(payload)))
        return {"success": True, "contact_id": payload.contact_id}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/contact/bulk", dependencies=[Depends(require_api_key)])
async def bulk_upsert(payload: BulkPayload):
    results = {"success": 0, "skipped": 0, "errors": []}
    for contact in payload.contacts:
        try:
            await store_contact(contact.contact_id, contact.dict(), embed_profile(_build_profile_text(contact)))
            results["success"] += 1
        except Exception as e:
            results["errors"].append({"contact_id": contact.contact_id, "error": str(e)}); results["skipped"] += 1
    return results

@app.get("/contact/{contact_id}", dependencies=[Depends(require_api_key)])
async def get_contact_by_id(contact_id: str):
    contact = await get_contact(contact_id)
    if not contact: raise HTTPException(status_code=404, detail="Contact not found")
    stakeholder_links = await get_stakeholders_for_contact(contact_id)
    buckets = await get_buckets_for_contact(contact_id)
    org_profile = await get_organization(contact.get("organization_id")) if contact.get("organization_id") else None
    return {"success": True, "data": contact, "initiative_links": stakeholder_links, "buckets": buckets, "org_profile": org_profile}

@app.put("/contact/{contact_id}", dependencies=[Depends(require_api_key)])
async def update_contact(contact_id: str, payload: ContactPayload):
    try:
        await store_contact(contact_id, payload.dict(), embed_profile(_build_profile_text(payload)))
        return {"success": True, "contact_id": contact_id}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/contacts", dependencies=[Depends(require_api_key)])
async def list_contacts(limit: int = 50, offset: int = 0):
    contacts = await get_all_contacts(limit=limit, offset=offset)
    total = await count_contacts()
    return {"success": True, "data": contacts, "count": total}

@app.get("/contacts/search", dependencies=[Depends(require_api_key)])
async def text_search(q: str, limit: int = 50):
    if not q or not q.strip(): raise HTTPException(status_code=400, detail="Query parameter 'q' is required")
    results = await text_search_contacts(q.strip(), limit=limit)
    return {"success": True, "query": q, "data": results, "count": len(results)}

@app.delete("/contact/{contact_id}", dependencies=[Depends(require_api_key)])
async def remove_contact(contact_id: str):
    await delete_contact(contact_id); return {"success": True}

@app.get("/match/{contact_id}", dependencies=[Depends(require_api_key)])
async def match_contact(contact_id: str, limit: int = 5):
    matches = await find_similar(contact_id, limit=limit)
    if matches is None: raise HTTPException(status_code=404, detail="Contact not found in vector DB")
    return {"contact_id": contact_id, "matches": matches}

@app.post("/search", dependencies=[Depends(require_api_key)])
async def search_contacts(request: SearchRequest):
    try:
        results = await find_matches_by_vector(embed_query(request.query), limit=request.top_k)
        return {"query": request.query, "results": results}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/draft", dependencies=[Depends(require_api_key)])
async def draft_intro_email(payload: DraftPayload):
    contact_a = await get_contact(payload.contact_a_id); contact_b = await get_contact(payload.contact_b_id)
    if not contact_a or not contact_b: raise HTTPException(status_code=404, detail="One or both contacts not found")
    return {"success": True, "draft": draft_intro(contact_a, contact_b)}

# ── CANDIDACY ─────────────────────────────────────────────────────────────────

@app.patch("/contact/{contact_id}/candidacy", dependencies=[Depends(require_api_key)])
async def update_candidacy(contact_id: str, payload: CandidacyUpdate):
    if payload.outreach_candidacy and payload.outreach_candidacy not in CANDIDACY_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(CANDIDACY_STATUSES)}")
    contact = await get_contact(contact_id)
    if not contact: raise HTTPException(status_code=404, detail="Contact not found")
    contact["outreach_candidacy"] = payload.outreach_candidacy
    profile_text = " | ".join(filter(None, [
        f"Name: {contact.get('full_name', '')}",
        f"Role: {contact.get('title_role', '')}",
        f"Org: {contact.get('organization', '')}",
        f"What I can offer: {contact.get('what_i_can_offer', '')}",
        f"What they offer: {contact.get('what_they_offer_me', '')}",
        f"Notes: {contact.get('notes', '')}",
    ]))
    await store_contact(contact_id, contact, embed_profile(profile_text))
    return {"success": True, "contact_id": contact_id, "outreach_candidacy": payload.outreach_candidacy}

# ── ON-DEMAND DRAFT ───────────────────────────────────────────────────────────

@app.post("/contact/{contact_id}/draft-outreach", dependencies=[Depends(require_api_key)])
async def generate_outreach_draft(contact_id: str, payload: DraftOutreachPayload):
    contact = await get_contact(contact_id)
    if not contact: raise HTTPException(status_code=404, detail="Contact not found")
    loop = asyncio.get_event_loop()
    draft = await loop.run_in_executor(
        None, draft_outreach_email, contact, payload.campaign_context, payload.your_goal or ""
    )
    return {"success": True, "contact_id": contact_id, "draft": draft}

# ── INITIATIVE MULTILINK ──────────────────────────────────────────────────────

@app.post("/contact/{contact_id}/link-initiatives", dependencies=[Depends(require_api_key)])
async def link_contact_to_initiatives(contact_id: str, payload: InitiativeLinkPayload):
    contact = await get_contact(contact_id)
    if not contact: raise HTTPException(status_code=404, detail="Contact not found")
    full_name = contact.get("full_name", "")
    existing_links = await get_stakeholders_for_contact(contact_id)
    existing_ini_ids = {l.get("initiative_id") for l in existing_links}
    created = []
    skipped = []
    for ini_id in payload.initiative_ids:
        if ini_id in existing_ini_ids:
            skipped.append(ini_id)
            continue
        stakeholder_id = f"STK-{int(time.time() * 1000)}"
        stk_data = {
            "stakeholder_id": stakeholder_id,
            "contact_id": contact_id,
            "full_name": full_name,
            "initiative_id": ini_id,
            "sub_project_id": "",
            "role": payload.role or "Warm Path",
            "action_needed": payload.action_needed or "None Yet",
            "engagement_status": "Not Contacted",
            "notes": "",
        }
        await upsert_stakeholder(stakeholder_id, contact_id, ini_id, stk_data)
        created.append(ini_id)
    return {"success": True, "contact_id": contact_id, "linked": created, "skipped_already_linked": skipped}

# ════════════════════════════════════════════════════════════════════════════
# BUCKETS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/buckets", dependencies=[Depends(require_api_key)])
async def list_buckets():
    data = await get_all_buckets(); return {"success": True, "data": data, "count": len(data)}

@app.get("/bucket/{bucket_id}", dependencies=[Depends(require_api_key)])
async def get_bucket_by_id(bucket_id: str):
    data = await get_bucket(bucket_id)
    if not data: raise HTTPException(status_code=404, detail="Bucket not found")
    return {"success": True, "data": data}

@app.get("/bucket/{bucket_id}/contacts", dependencies=[Depends(require_api_key)])
async def list_contacts_in_bucket(bucket_id: str):
    contacts = await get_contacts_in_bucket(bucket_id); return {"success": True, "data": contacts, "count": len(contacts)}

@app.get("/contact/{contact_id}/buckets", dependencies=[Depends(require_api_key)])
async def get_contact_bucket_membership(contact_id: str):
    data = await get_buckets_for_contact(contact_id); return {"success": True, "data": data}

@app.get("/initiative/{initiative_id}/buckets", dependencies=[Depends(require_api_key)])
async def list_buckets_for_initiative(initiative_id: str):
    data = await get_buckets_for_initiative(initiative_id); return {"success": True, "data": data, "count": len(data)}

@app.post("/bucket", dependencies=[Depends(require_api_key)])
async def create_bucket(payload: BucketPayload):
    bucket_id = payload.bucket_id or f"BKT-{int(time.time() * 1000)}"; data = payload.dict(); data["bucket_id"] = bucket_id
    await upsert_bucket(bucket_id, data); return {"success": True, "bucket_id": bucket_id}

@app.put("/bucket/{bucket_id}", dependencies=[Depends(require_api_key)])
async def update_bucket(bucket_id: str, payload: BucketPayload):
    existing = await get_bucket(bucket_id)
    if not existing: raise HTTPException(status_code=404, detail="Bucket not found")
    data = {k: v for k, v in payload.dict().items() if v is not None}; data["bucket_id"] = bucket_id
    await upsert_bucket(bucket_id, data); return {"success": True}

@app.post("/bucket/{bucket_id}/members", dependencies=[Depends(require_api_key)])
async def add_member_to_bucket(bucket_id: str, payload: BucketMemberPayload):
    bucket = await get_bucket(bucket_id)
    if not bucket: raise HTTPException(status_code=404, detail="Bucket not found")
    await add_contact_to_bucket(bucket_id, payload.contact_id)
    return {"success": True, "bucket_id": bucket_id, "contact_id": payload.contact_id}

@app.delete("/bucket/{bucket_id}/members/{contact_id}", dependencies=[Depends(require_api_key)])
async def remove_member_from_bucket(bucket_id: str, contact_id: str):
    await remove_contact_from_bucket(bucket_id, contact_id); return {"success": True}

@app.delete("/bucket/{bucket_id}", dependencies=[Depends(require_api_key)])
async def remove_bucket(bucket_id: str):
    await delete_bucket(bucket_id); return {"success": True}

@app.post("/bucket/from-search", dependencies=[Depends(require_api_key)])
async def create_bucket_from_search(payload: BucketFromSearchPayload):
    try:
        matches = await find_matches_by_vector(embed_query(payload.description), limit=payload.top_k)
        if not payload.auto_commit:
            return {"success": True, "mode": "review", "description": payload.description, "proposed_bucket_name": payload.bucket_name, "matches": matches, "count": len(matches)}
        bucket_id = f"BKT-{int(time.time() * 1000)}"
        await upsert_bucket(bucket_id, {"bucket_id": bucket_id, "name": payload.bucket_name, "description": payload.description, "color": payload.bucket_color or "#6BC47F", "initiative_id": payload.initiative_id or ""})
        added = []
        for match in matches:
            if match.get("contact_id"):
                await add_contact_to_bucket(bucket_id, match["contact_id"]); added.append(match["contact_id"])
        return {"success": True, "mode": "committed", "bucket_id": bucket_id, "bucket_name": payload.bucket_name, "contacts_added": len(added), "contacts": matches}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

# ── LEGACY BATCH ENRICH (kept for backward compat) ────────────────────────────

@app.post("/bucket/{bucket_id}/enrich", dependencies=[Depends(require_api_key)])
async def enrich_bucket(bucket_id: str, payload: BucketEnrichPayload):
    bucket = await get_bucket(bucket_id)
    if not bucket: raise HTTPException(status_code=404, detail="Bucket not found")

    all_contacts = await get_contacts_in_bucket(bucket_id)
    total = len(all_contacts)
    batch = all_contacts[payload.offset: payload.offset + payload.batch_size]

    if not batch:
        return {
            "success": True, "bucket_id": bucket_id, "total_in_bucket": total,
            "batch_offset": payload.offset, "batch_size": payload.batch_size,
            "processed": 0, "results": [], "message": "No contacts in this batch."
        }

    loop = asyncio.get_event_loop()
    org_cache = await loop.run_in_executor(None, enrich_org_pass, batch)

    results = []
    for i, contact in enumerate(batch):
        result = await loop.run_in_executor(None, enrich_and_draft, contact, payload.campaign_context, org_cache)
        results.append(result)

        if payload.write_back and result.get("enrichment", {}).get("enrichment_status") == "enriched":
            try:
                enrichment = result["enrichment"]
                existing = await get_contact(contact["contact_id"])
                if existing:
                    if enrichment.get("what_i_can_offer"):
                        existing["what_i_can_offer"] = enrichment["what_i_can_offer"]
                    if enrichment.get("what_they_offer_me"):
                        existing["what_they_offer_me"] = enrichment["what_they_offer_me"]
                    if enrichment.get("contact_type"):
                        existing["contact_type"] = enrichment["contact_type"]
                    org_ctx = enrichment.get("org_description", "")
                    person_ctx = enrichment.get("person_summary", "")
                    recent = enrichment.get("org_recent_activity", "")
                    parts = []
                    if org_ctx: parts.append(f"Org: {org_ctx}")
                    if person_ctx: parts.append(f"Person: {person_ctx}")
                    if recent: parts.append(f"Recent: {recent}")
                    if parts:
                        enrich_note = f"\n[Enriched {time.strftime('%Y-%m-%d')}] " + " | ".join(parts)
                        existing_notes = existing.get("notes", "") or ""
                        if "[Enriched" not in existing_notes:
                            existing["notes"] = (existing_notes + enrich_note).strip()
                    profile_text = " | ".join(filter(None, [
                        f"Name: {existing.get('full_name', '')}",
                        f"Role: {existing.get('title_role', '')}",
                        f"Org: {existing.get('organization', '')}",
                        f"What I can offer: {existing.get('what_i_can_offer', '')}",
                        f"What they offer me: {existing.get('what_they_offer_me', '')}",
                        f"Notes: {existing.get('notes', '')}",
                    ]))
                    await store_contact(existing["contact_id"], existing, embed_profile(profile_text))
            except Exception:
                pass

        if i < len(batch) - 1:
            await asyncio.sleep(15)

    has_more = (payload.offset + payload.batch_size) < total
    return {
        "success": True,
        "bucket_id": bucket_id,
        "bucket_name": bucket.get("name", ""),
        "total_in_bucket": total,
        "batch_offset": payload.offset,
        "batch_size": payload.batch_size,
        "processed": len(results),
        "has_more": has_more,
        "next_offset": payload.offset + payload.batch_size if has_more else None,
        "results": results,
    }

# ── NEW: BACKGROUND ENRICH-ALL ────────────────────────────────────────────────

@app.post("/bucket/{bucket_id}/enrich-all", dependencies=[Depends(require_api_key)])
async def enrich_bucket_all(bucket_id: str, payload: BucketEnrichAllPayload, background_tasks: BackgroundTasks):
    """
    Kick off a background job that enriches every unenriched contact in the bucket,
    one at a time, with a 3s pause between each.
    Skips contacts that already have what_i_can_offer populated.
    Tracks estimated cost and halts if spend exceeds $5.
    Returns a job_id immediately. Poll /bucket/{bucket_id}/enrich-status?job_id=... to check progress.
    """
    bucket = await get_bucket(bucket_id)
    if not bucket: raise HTTPException(status_code=404, detail="Bucket not found")

    job_id = f"JOB-{int(time.time() * 1000)}"
    _enrich_jobs[job_id] = {
        "job_id": job_id,
        "bucket_id": bucket_id,
        "status": "queued",
        "total": 0,
        "to_enrich": 0,
        "processed": 0,
        "succeeded": 0,
        "skipped_already_done": 0,
        "failed": [],
        "estimated_cost_usd": 0.0,
        "cost_halted": False,
        "current_contact": None,
        "message": None,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    background_tasks.add_task(_run_enrich_all_job, job_id, bucket_id, payload.campaign_context)

    return {
        "success": True,
        "job_id": job_id,
        "bucket_id": bucket_id,
        "message": "Enrichment job started in background. Poll /bucket/{bucket_id}/enrich-status?job_id={job_id} to check progress.",
        "cost_warning_threshold_usd": COST_WARNING_THRESHOLD,
    }


@app.get("/bucket/{bucket_id}/enrich-status", dependencies=[Depends(require_api_key)])
async def get_enrich_status(bucket_id: str, job_id: str):
    """
    Check the status of a background enrichment job.
    """
    job = _enrich_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found. Jobs are cleared on Railway restart.")
    return {"success": True, "job": job}

# ════════════════════════════════════════════════════════════════════════════
# INITIATIVES / SUB-PROJECTS / STAKEHOLDERS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/initiatives", dependencies=[Depends(require_api_key)])
async def list_initiatives():
    data = await get_all_initiatives(); return {"success": True, "data": data, "count": len(data)}

@app.get("/initiative/{initiative_id}", dependencies=[Depends(require_api_key)])
async def get_initiative_by_id(initiative_id: str):
    data = await get_initiative(initiative_id)
    if not data: raise HTTPException(status_code=404, detail="Initiative not found")
    return {"success": True, "data": data, "sub_projects": await get_sub_projects_for_initiative(initiative_id), "stakeholders": await get_stakeholders_for_initiative(initiative_id), "action_items": await get_action_items_for_initiative(initiative_id), "buckets": await get_buckets_for_initiative(initiative_id)}

@app.post("/initiative", dependencies=[Depends(require_api_key)])
async def create_initiative(payload: InitiativePayload):
    initiative_id = payload.initiative_id or f"INI-{int(time.time() * 1000)}"; data = payload.dict(); data["initiative_id"] = initiative_id
    await upsert_initiative(initiative_id, data); return {"success": True, "initiative_id": initiative_id}

@app.put("/initiative/{initiative_id}", dependencies=[Depends(require_api_key)])
async def update_initiative(initiative_id: str, payload: InitiativePayload):
    existing = await get_initiative(initiative_id)
    if not existing: raise HTTPException(status_code=404, detail="Initiative not found")
    data = {**existing, **{k: v for k, v in payload.dict().items() if v is not None}}; data["initiative_id"] = initiative_id
    await upsert_initiative(initiative_id, data); return {"success": True}

@app.patch("/initiative/{initiative_id}/status", dependencies=[Depends(require_api_key)])
async def update_initiative_status(initiative_id: str, payload: InitiativeStatusUpdate):
    existing = await get_initiative(initiative_id)
    if not existing: raise HTTPException(status_code=404, detail="Initiative not found")
    existing["status"] = payload.status; await upsert_initiative(initiative_id, existing)
    return {"success": True, "initiative_id": initiative_id, "status": payload.status}

@app.delete("/initiative/{initiative_id}", dependencies=[Depends(require_api_key)])
async def remove_initiative(initiative_id: str):
    await delete_initiative(initiative_id); return {"success": True}

@app.get("/initiative/{initiative_id}/sub-projects", dependencies=[Depends(require_api_key)])
async def list_sub_projects(initiative_id: str):
    return {"success": True, "data": await get_sub_projects_for_initiative(initiative_id)}

@app.post("/sub-project", dependencies=[Depends(require_api_key)])
async def create_sub_project(payload: SubProjectPayload):
    sub_project_id = payload.sub_project_id or f"SUB-{int(time.time() * 1000)}"; data = payload.dict(); data["sub_project_id"] = sub_project_id
    await upsert_sub_project(sub_project_id, payload.initiative_id, data); return {"success": True, "sub_project_id": sub_project_id}

@app.put("/sub-project/{sub_project_id}", dependencies=[Depends(require_api_key)])
async def update_sub_project(sub_project_id: str, payload: SubProjectPayload):
    data = payload.dict(); data["sub_project_id"] = sub_project_id
    await upsert_sub_project(sub_project_id, payload.initiative_id, data); return {"success": True}

@app.delete("/sub-project/{sub_project_id}", dependencies=[Depends(require_api_key)])
async def remove_sub_project(sub_project_id: str):
    await delete_sub_project(sub_project_id); return {"success": True}

@app.get("/initiative/{initiative_id}/stakeholders", dependencies=[Depends(require_api_key)])
async def list_stakeholders(initiative_id: str):
    return {"success": True, "data": await get_stakeholders_for_initiative(initiative_id)}

@app.get("/contact/{contact_id}/initiatives", dependencies=[Depends(require_api_key)])
async def get_contact_initiatives(contact_id: str):
    data = await get_stakeholders_for_contact(contact_id); return {"success": True, "data": data, "count": len(data)}

@app.post("/stakeholder", dependencies=[Depends(require_api_key)])
async def create_stakeholder(payload: StakeholderPayload):
    stakeholder_id = payload.stakeholder_id or f"STK-{int(time.time() * 1000)}"; data = payload.dict(); data["stakeholder_id"] = stakeholder_id
    await upsert_stakeholder(stakeholder_id, payload.contact_id or "", payload.initiative_id, data); return {"success": True, "stakeholder_id": stakeholder_id}

@app.patch("/stakeholder/{stakeholder_id}/engagement", dependencies=[Depends(require_api_key)])
async def update_stakeholder_engagement(stakeholder_id: str, payload: StakeholderEngagementUpdate):
    from db import _conn; import json as _json; conn = await _conn()
    try:
        row = await conn.fetchrow("SELECT data, contact_id, initiative_id FROM stakeholders WHERE stakeholder_id = $1", stakeholder_id)
        if not row: raise HTTPException(status_code=404, detail="Stakeholder not found")
        data = _json.loads(row["data"]); data["engagement_status"] = payload.engagement_status
        if payload.notes: data["notes"] = data.get("notes", "") + f"\n{payload.notes}"
        await upsert_stakeholder(stakeholder_id, row["contact_id"], row["initiative_id"], data); return {"success": True}
    finally: await conn.close()

@app.delete("/stakeholder/{stakeholder_id}", dependencies=[Depends(require_api_key)])
async def remove_stakeholder(stakeholder_id: str):
    await delete_stakeholder(stakeholder_id); return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# ACTIVATION ANGLES / ACTION ITEMS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/activation-angles", dependencies=[Depends(require_api_key)])
async def list_activation_angles():
    return {"success": True, "data": await get_all_activation_angles()}

@app.post("/activation-angle", dependencies=[Depends(require_api_key)])
async def create_activation_angle(payload: ActivationAnglePayload):
    angle_id = payload.angle_id or f"ANG-{int(time.time() * 1000)}"; data = payload.dict(); data["angle_id"] = angle_id
    await upsert_activation_angle(angle_id, data); return {"success": True, "angle_id": angle_id}

@app.put("/activation-angle/{angle_id}", dependencies=[Depends(require_api_key)])
async def update_activation_angle(angle_id: str, payload: ActivationAnglePayload):
    data = payload.dict(); data["angle_id"] = angle_id; await upsert_activation_angle(angle_id, data); return {"success": True}

@app.delete("/activation-angle/{angle_id}", dependencies=[Depends(require_api_key)])
async def remove_activation_angle(angle_id: str):
    await delete_activation_angle(angle_id); return {"success": True}

@app.get("/action-items", dependencies=[Depends(require_api_key)])
async def list_open_action_items(due_before: Optional[str] = None):
    data = await get_open_action_items(due_before=due_before); return {"success": True, "data": data, "count": len(data)}

@app.get("/initiative/{initiative_id}/action-items", dependencies=[Depends(require_api_key)])
async def list_action_items_for_initiative(initiative_id: str):
    return {"success": True, "data": await get_action_items_for_initiative(initiative_id)}

@app.post("/action-item", dependencies=[Depends(require_api_key)])
async def create_action_item(payload: ActionItemPayload):
    action_id = payload.action_id or f"ACT-{int(time.time() * 1000)}"; data = payload.dict(); data["action_id"] = action_id
    await upsert_action_item(action_id, payload.initiative_id or "SPRINT", payload.stakeholder_id or "", data); return {"success": True, "action_id": action_id}

@app.put("/action-item/{action_id}", dependencies=[Depends(require_api_key)])
async def update_action_item(action_id: str, payload: ActionItemPayload):
    data = payload.dict(); data["action_id"] = action_id; await upsert_action_item(action_id, payload.initiative_id or "SPRINT", payload.stakeholder_id or "", data); return {"success": True}

@app.patch("/action-item/{action_id}/status", dependencies=[Depends(require_api_key)])
async def update_action_item_status(action_id: str, payload: ActionItemStatusUpdate):
    from db import _conn; import json as _json; conn = await _conn()
    try:
        row = await conn.fetchrow("SELECT data, initiative_id, stakeholder_id FROM action_items WHERE action_id = $1", action_id)
        if not row: raise HTTPException(status_code=404, detail="Action item not found")
        data = _json.loads(row["data"]); data["status"] = payload.status
        if payload.completed_date: data["completed_date"] = payload.completed_date
        if payload.google_task_id: data["google_task_id"] = payload.google_task_id
        await upsert_action_item(action_id, row["initiative_id"], row["stakeholder_id"], data); return {"success": True}
    finally: await conn.close()

@app.get("/action-item/by-google-task/{google_task_id}", dependencies=[Depends(require_api_key)])
async def get_by_google_task_id(google_task_id: str):
    data = await get_action_item_by_google_task_id(google_task_id)
    if not data: raise HTTPException(status_code=404, detail="No action item found for this Google Task ID")
    return {"success": True, "data": data}

@app.delete("/action-item/{action_id}", dependencies=[Depends(require_api_key)])
async def remove_action_item(action_id: str):
    await delete_action_item(action_id); return {"success": True}

# ════════════════════════════════════════════════════════════════════════════
# CONTENT / FOLLOW-UPS / EVENTS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/content", dependencies=[Depends(require_api_key)])
async def list_content():
    return {"success": True, "data": await get_all_content(), "count": len(await get_all_content())}

@app.get("/content/{content_id}", dependencies=[Depends(require_api_key)])
async def get_content_by_id(content_id: str):
    data = await get_content(content_id)
    if not data: raise HTTPException(status_code=404, detail="Content not found")
    return {"success": True, "data": data}

@app.post("/content", dependencies=[Depends(require_api_key)])
async def upsert_content(payload: ContentPayload):
    try:
        content_id = payload.content_id or f"C-{int(time.time() * 1000)}"; data = payload.dict(); data["content_id"] = content_id
        await store_content(content_id, data, embed_profile(_build_content_text(payload))); return {"success": True, "content_id": content_id}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.put("/content/{content_id}", dependencies=[Depends(require_api_key)])
async def update_content(content_id: str, payload: ContentPayload):
    try:
        data = payload.dict(); data["content_id"] = content_id
        await store_content(content_id, data, embed_profile(_build_content_text(payload))); return {"success": True, "content_id": content_id}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.patch("/content/{content_id}/status", dependencies=[Depends(require_api_key)])
async def update_content_status(content_id: str, payload: ContentStatusUpdate):
    from db import _conn; import json as _json; conn = await _conn()
    try:
        row = await conn.fetchrow("SELECT data, embedding FROM content WHERE content_id = $1", content_id)
        if not row: raise HTTPException(status_code=404, detail="Content not found")
        data = _json.loads(row["data"]); data["status"] = payload.status
        if payload.prismm_sync is not None: data["prismm_sync"] = payload.prismm_sync
        existing_vector = list(row["embedding"]) if row["embedding"] else None
        if existing_vector: await store_content(content_id, data, existing_vector)
        else: await conn.execute("UPDATE content SET data = $1, updated_at = NOW() WHERE content_id = $2", _json.dumps(data), content_id)
        return {"success": True}
    finally: await conn.close()

@app.post("/content/search", dependencies=[Depends(require_api_key)])
async def search_content(request: SearchRequest):
    try: return {"query": request.query, "results": await search_content_by_vector(embed_query(request.query), limit=request.top_k)}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.delete("/content/{content_id}", dependencies=[Depends(require_api_key)])
async def remove_content(content_id: str):
    await delete_content(content_id); return {"success": True}

@app.get("/follow-ups/open", dependencies=[Depends(require_api_key)])
async def list_open_follow_ups():
    data = await get_open_follow_ups(); return {"success": True, "data": data, "count": len(data)}

@app.get("/follow-ups/overdue", dependencies=[Depends(require_api_key)])
async def list_overdue_follow_ups(as_of: Optional[str] = None):
    from datetime import date; as_of_date = as_of or date.today().isoformat()
    data = await get_overdue_follow_ups(as_of_date); return {"success": True, "data": data, "count": len(data), "as_of": as_of_date}

@app.get("/contact/{contact_id}/follow-ups", dependencies=[Depends(require_api_key)])
async def list_follow_ups_for_contact(contact_id: str):
    data = await get_follow_ups_for_contact(contact_id); return {"success": True, "data": data, "count": len(data)}

@app.get("/follow-up/{follow_up_id}", dependencies=[Depends(require_api_key)])
async def get_follow_up_by_id(follow_up_id: str):
    data = await get_follow_up(follow_up_id)
    if not data: raise HTTPException(status_code=404, detail="Follow-up not found")
    return {"success": True, "data": data}

@app.post("/follow-up", dependencies=[Depends(require_api_key)])
async def upsert_follow_up(payload: FollowUpPayload):
    try:
        follow_up_id = payload.follow_up_id or f"FU-{int(time.time() * 1000)}"; data = payload.dict(); data["follow_up_id"] = follow_up_id
        await store_follow_up(follow_up_id, payload.contact_id or "", data, embed_profile(_build_follow_up_text(payload))); return {"success": True, "follow_up_id": follow_up_id}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.put("/follow-up/{follow_up_id}", dependencies=[Depends(require_api_key)])
async def update_follow_up(follow_up_id: str, payload: FollowUpPayload):
    try:
        data = payload.dict(); data["follow_up_id"] = follow_up_id
        await store_follow_up(follow_up_id, payload.contact_id or "", data, embed_profile(_build_follow_up_text(payload))); return {"success": True, "follow_up_id": follow_up_id}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.patch("/follow-up/{follow_up_id}/status", dependencies=[Depends(require_api_key)])
async def update_follow_up_status(follow_up_id: str, payload: FollowUpStatusUpdate):
    from db import _conn; import json as _json; conn = await _conn()
    try:
        row = await conn.fetchrow("SELECT data, contact_id, embedding FROM follow_ups WHERE follow_up_id = $1", follow_up_id)
        if not row: raise HTTPException(status_code=404, detail="Follow-up not found")
        data = _json.loads(row["data"]); data["status"] = payload.status
        if payload.completed_date: data["completed_date"] = payload.completed_date
        existing_vector = list(row["embedding"]) if row["embedding"] else None
        if existing_vector: await store_follow_up(follow_up_id, row["contact_id"], data, existing_vector)
        else: await conn.execute("UPDATE follow_ups SET data = $1, updated_at = NOW() WHERE follow_up_id = $2", _json.dumps(data), follow_up_id)
        return {"success": True, "follow_up_id": follow_up_id, "status": payload.status}
    finally: await conn.close()

@app.post("/follow-ups/search", dependencies=[Depends(require_api_key)])
async def search_follow_ups(request: SearchRequest):
    try: return {"query": request.query, "results": await search_follow_ups_by_vector(embed_query(request.query), limit=request.top_k)}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.delete("/follow-up/{follow_up_id}", dependencies=[Depends(require_api_key)])
async def remove_follow_up(follow_up_id: str):
    await delete_follow_up(follow_up_id); return {"success": True}

@app.get("/events", dependencies=[Depends(require_api_key)])
async def list_events(type: Optional[str] = None, venture: Optional[str] = None):
    data = await get_all_events(event_type=type, venture=venture); return {"success": True, "data": data, "count": len(data)}

@app.get("/event/{event_id}", dependencies=[Depends(require_api_key)])
async def get_event_by_id(event_id: str):
    data = await get_event(event_id)
    if not data: raise HTTPException(status_code=404, detail="Event not found")
    guests = await get_guests_for_event(event_id)
    return {"success": True, "data": data, "guests": guests, "guest_summary": {"total": len(guests), "confirmed": sum(1 for g in guests if g.get("guest_status") == "Confirmed"), "attended": sum(1 for g in guests if g.get("guest_status") == "Attended")}}

@app.post("/event", dependencies=[Depends(require_api_key)])
async def create_event(payload: EventPayload):
    event_id = payload.event_id or f"EVT-{int(time.time() * 1000)}"; data = payload.dict(); data["event_id"] = event_id
    await upsert_event(event_id, data); return {"success": True, "event_id": event_id}

@app.put("/event/{event_id}", dependencies=[Depends(require_api_key)])
async def update_event(event_id: str, payload: EventPayload):
    existing = await get_event(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    data = {**existing, **{k: v for k, v in payload.dict().items() if v is not None and v != ""}}; data["event_id"] = event_id
    await upsert_event(event_id, data); return {"success": True}

@app.patch("/event/{event_id}/status", dependencies=[Depends(require_api_key)])
async def update_event_status(event_id: str, payload: EventStatusUpdate):
    existing = await get_event(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    existing["status"] = payload.status; await upsert_event(event_id, existing)
    return {"success": True, "event_id": event_id, "status": payload.status}

@app.delete("/event/{event_id}", dependencies=[Depends(require_api_key)])
async def remove_event(event_id: str):
    await delete_event(event_id); return {"success": True}

@app.post("/event-guest", dependencies=[Depends(require_api_key)])
async def add_event_guest(payload: EventGuestPayload):
    guest_id = payload.guest_id or f"GST-{int(time.time() * 1000)}"; data = payload.dict(); data["guest_id"] = guest_id
    await upsert_event_guest(guest_id, payload.event_id, data); return {"success": True, "guest_id": guest_id}

@app.patch("/event-guest/{guest_id}", dependencies=[Depends(require_api_key)])
async def update_event_guest(guest_id: str, payload: EventGuestUpdate):
    from db import _conn; import json as _json; conn = await _conn()
    try:
        row = await conn.fetchrow("SELECT data, event_id FROM event_guests WHERE guest_id = $1", guest_id)
        if not row: raise HTTPException(status_code=404, detail="Guest not found")
        data = _json.loads(row["data"])
        if payload.guest_status: data["guest_status"] = payload.guest_status
        if payload.notes: data["notes"] = payload.notes
        await upsert_event_guest(guest_id, row["event_id"], data); return {"success": True}
    finally: await conn.close()

@app.delete("/event-guest/{guest_id}", dependencies=[Depends(require_api_key)])
async def remove_event_guest(guest_id: str):
    await delete_event_guest(guest_id); return {"success": True}

@app.get("/event/{event_id}/guests", dependencies=[Depends(require_api_key)])
async def list_event_guests(event_id: str):
    data = await get_guests_for_event(event_id); return {"success": True, "data": data, "count": len(data)}
