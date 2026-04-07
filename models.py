"""
Pydantic request/response models for all entities.
Contacts model lives in main.py — kept separate for legacy reasons.
"""
from pydantic import BaseModel
from typing import Optional


# ── ORGANIZATIONS ─────────────────────────────────────────────────────────────

class OrganizationPayload(BaseModel):
    org_id: Optional[str] = None              # auto-generated if omitted: ORG-{timestamp}
    name: str                                 # Canonical org name e.g. "gener8tor"
    org_type: Optional[str] = ""             # Accelerator / VC / Incubator / Nonprofit / Venture Studio / Foundation / etc.
    org_focus: Optional[str] = ""            # Primary domain in 5-10 words
    description: Optional[str] = ""          # 2-3 sentences describing what they do
    website: Optional[str] = ""
    linkedin_url: Optional[str] = ""
    location: Optional[str] = ""             # HQ city / state
    recent_activity: Optional[str] = ""      # Latest notable program, cohort, announcement
    conversation_hook: Optional[str] = ""    # Best thing to reference in outreach
    last_enriched: Optional[str] = None      # ISO date string — when Claude last researched this org
    notes: Optional[str] = ""


# ── INITIATIVES ───────────────────────────────────────────────────────────────

class InitiativePayload(BaseModel):
    initiative_id: Optional[str] = None
    initiative_name: str
    venture: Optional[str] = ""
    goal: Optional[str] = ""
    core_question: Optional[str] = ""
    status: Optional[str] = "Brain Dump"
    priority: Optional[str] = "Medium"
    timeline: Optional[str] = ""
    brand: Optional[str] = ""
    distribution: Optional[str] = ""
    format: Optional[str] = ""
    budget: Optional[str] = ""
    brain_dump: Optional[str] = ""
    phoebe_cadence: Optional[str] = "Weekly"
    last_phoebe_checkin: Optional[str] = None
    notes: Optional[str] = ""


class InitiativeStatusUpdate(BaseModel):
    status: str


# ── SUB-PROJECTS ──────────────────────────────────────────────────────────────

class SubProjectPayload(BaseModel):
    sub_project_id: Optional[str] = None
    initiative_id: str
    sub_project_name: str
    description: Optional[str] = ""
    status: Optional[str] = "Not Started"
    priority: Optional[str] = "Medium"
    dependencies: Optional[str] = ""
    owner: Optional[str] = "Keyona"
    notes: Optional[str] = ""


# ── STAKEHOLDERS ──────────────────────────────────────────────────────────────

class StakeholderPayload(BaseModel):
    stakeholder_id: Optional[str] = None
    contact_id: Optional[str] = ""
    full_name: str
    initiative_id: str
    sub_project_id: Optional[str] = ""
    role: Optional[str] = ""
    action_needed: Optional[str] = "None Yet"
    engagement_status: Optional[str] = "Not Contacted"
    notes: Optional[str] = ""


class StakeholderEngagementUpdate(BaseModel):
    engagement_status: str
    notes: Optional[str] = None


# ── ACTIVATION ANGLES ─────────────────────────────────────────────────────────

class ActivationAnglePayload(BaseModel):
    angle_id: Optional[str] = None
    angle_name: str
    description: Optional[str] = ""
    template: Optional[str] = ""
    best_for: Optional[str] = ""
    used_in: Optional[str] = ""
    effectiveness_notes: Optional[str] = ""


# ── ACTION ITEMS ──────────────────────────────────────────────────────────────

class ActionItemPayload(BaseModel):
    action_id: Optional[str] = None
    initiative_id: Optional[str] = ""
    sub_project_id: Optional[str] = ""
    stakeholder_id: Optional[str] = ""
    action_type: Optional[str] = ""
    description: str
    status: Optional[str] = "Open"
    priority: Optional[str] = "Medium"
    due_date: Optional[str] = None
    google_task_id: Optional[str] = ""
    google_task_list: Optional[str] = ""
    source: Optional[str] = "Manual"
    phoebe_tracking: Optional[bool] = False
    completed_date: Optional[str] = None


class ActionItemStatusUpdate(BaseModel):
    status: str
    completed_date: Optional[str] = None
    google_task_id: Optional[str] = None


# ── CONTENT ───────────────────────────────────────────────────────────────────

class ContentPayload(BaseModel):
    content_id: Optional[str] = None
    content_name: str
    content_type: Optional[str] = ""
    venture: Optional[str] = ""
    initiative_tags: Optional[str] = ""
    status: Optional[str] = "Idea"
    activation_angle: Optional[str] = ""
    asset_link: Optional[str] = ""
    approval_required: Optional[str] = "No"
    prismm_sync: Optional[str] = ""
    notes: Optional[str] = ""


class ContentStatusUpdate(BaseModel):
    status: str
    prismm_sync: Optional[str] = None


# ── FOLLOW-UPS ────────────────────────────────────────────────────────────────

class FollowUpPayload(BaseModel):
    follow_up_id: Optional[str] = None
    contact_name: str
    contact_id: Optional[str] = ""
    meeting_name: Optional[str] = ""
    meeting_date: Optional[str] = None
    next_action: Optional[str] = ""
    next_action_date: Optional[str] = None
    venture: Optional[str] = ""
    transcript_link: Optional[str] = ""
    draft_link: Optional[str] = ""
    status: Optional[str] = "Open"
    completed_date: Optional[str] = None
    notes: Optional[str] = ""


class FollowUpStatusUpdate(BaseModel):
    status: str
    completed_date: Optional[str] = None


# ── EVENTS ────────────────────────────────────────────────────────────────────

class EventPayload(BaseModel):
    event_id: Optional[str] = None
    event_name: str
    event_type: Optional[str] = ""
    venture: Optional[str] = ""
    date: Optional[str] = None
    location: Optional[str] = ""
    status: Optional[str] = "Planning"
    initiative_id: Optional[str] = ""
    description: Optional[str] = ""
    notes: Optional[str] = ""


class EventStatusUpdate(BaseModel):
    status: str


# ── EVENT GUESTS ──────────────────────────────────────────────────────────────

class EventGuestPayload(BaseModel):
    guest_id: Optional[str] = None
    event_id: str
    contact_id: Optional[str] = ""
    full_name: str
    role: Optional[str] = ""
    guest_status: Optional[str] = "Invited"
    notes: Optional[str] = ""


class EventGuestUpdate(BaseModel):
    role: Optional[str] = None
    guest_status: Optional[str] = None
    notes: Optional[str] = None
