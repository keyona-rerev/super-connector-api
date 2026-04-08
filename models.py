"""
Pydantic request/response models for all entities.
Contacts model lives in main.py — kept separate for legacy reasons.
"""
from pydantic import BaseModel
from typing import Optional, List


# ── ORGANIZATIONS ─────────────────────────────────────────────────────────────

class OrganizationPayload(BaseModel):
    org_id: Optional[str] = None
    name: str
    org_type: Optional[str] = ""
    org_focus: Optional[str] = ""
    description: Optional[str] = ""
    website: Optional[str] = ""
    linkedin_url: Optional[str] = ""
    location: Optional[str] = ""
    recent_activity: Optional[str] = ""
    conversation_hook: Optional[str] = ""
    last_enriched: Optional[str] = None
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


class BucketAnglesUpdate(BaseModel):
    """Set the bucket-level activation angle defaults. Replaces the full list."""
    angle_ids: List[str]


class ContactBucketAnglesUpdate(BaseModel):
    """
    Override activation angles for a specific contact within a bucket.
    Supplying an empty list clears the override and keeps the row (contact reverts to bucket defaults on next read).
    Call DELETE /bucket/{id}/members/{contact_id}/angles to fully remove the override row.
    """
    angle_ids: List[str]


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


# ── CANDIDACY ─────────────────────────────────────────────────────────────────

CANDIDACY_STATUSES = [
    "Candidate - Not Yet Qualified",
    "Candidate - Qualified",
    "Candidate - Passed",
    "Candidate - Contacted",
    "Candidate - Responded",
]

class CandidacyUpdate(BaseModel):
    outreach_candidacy: str  # must be one of CANDIDACY_STATUSES or empty string to clear


# ── ON-DEMAND DRAFT ───────────────────────────────────────────────────────────

class DraftOutreachPayload(BaseModel):
    campaign_context: str
    your_goal: Optional[str] = ""  # e.g. "I want to send her founders for the gener8tor programs"


# ── INITIATIVE LINK (for multiselect from contact profile) ───────────────────

class InitiativeLinkPayload(BaseModel):
    initiative_ids: List[str]                    # list of initiative IDs to link
    role: Optional[str] = "Warm Path"            # default stakeholder role
    action_needed: Optional[str] = "None Yet"    # default action
