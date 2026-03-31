"""
Pydantic request/response models for all entities.
Contacts model lives in main.py — kept separate for legacy reasons.
"""
from pydantic import BaseModel
from typing import Optional


# ── INITIATIVES ───────────────────────────────────────────────────────────────

class InitiativePayload(BaseModel):
    initiative_id: Optional[str] = None          # auto-generated if omitted
    initiative_name: str
    venture: Optional[str] = ""                  # ReRev / Prismm / BTC / Personal / Sekhmetic
    goal: Optional[str] = ""
    core_question: Optional[str] = ""
    status: Optional[str] = "Brain Dump"         # Brain Dump / Planning / Active / Paused / Complete
    priority: Optional[str] = "Medium"           # Critical / High / Medium / Low / Parked
    timeline: Optional[str] = ""
    brand: Optional[str] = ""
    distribution: Optional[str] = ""
    format: Optional[str] = ""
    budget: Optional[str] = ""
    brain_dump: Optional[str] = ""
    phoebe_cadence: Optional[str] = "Weekly"     # Daily / Every 2-3 days / Weekly / Biweekly / Monthly / None
    last_phoebe_checkin: Optional[str] = None    # ISO date string
    notes: Optional[str] = ""


class InitiativeStatusUpdate(BaseModel):
    status: str


# ── SUB-PROJECTS ──────────────────────────────────────────────────────────────

class SubProjectPayload(BaseModel):
    sub_project_id: Optional[str] = None
    initiative_id: str
    sub_project_name: str
    description: Optional[str] = ""
    status: Optional[str] = "Not Started"        # Not Started / In Progress / Blocked / Complete
    priority: Optional[str] = "Medium"
    dependencies: Optional[str] = ""
    owner: Optional[str] = "Keyona"
    notes: Optional[str] = ""


# ── STAKEHOLDERS ──────────────────────────────────────────────────────────────

class StakeholderPayload(BaseModel):
    stakeholder_id: Optional[str] = None
    contact_id: Optional[str] = ""              # FK to contacts table — can be blank until linked
    full_name: str
    initiative_id: str
    sub_project_id: Optional[str] = ""
    role: Optional[str] = ""                    # Interview Subject / Advisor / Committee / Sponsor Prospect /
                                                # Customer / Collaborator / Warm Path / Perspective Only
    action_needed: Optional[str] = "None Yet"   # Outreach / Interview / Follow Up / Consider Perspective / None Yet
    engagement_status: Optional[str] = "Not Contacted"  # Not Contacted / Contacted / Scheduled / Active / Complete / Declined
    notes: Optional[str] = ""


class StakeholderEngagementUpdate(BaseModel):
    engagement_status: str
    notes: Optional[str] = None


# ── ACTIVATION ANGLES ─────────────────────────────────────────────────────────

class ActivationAnglePayload(BaseModel):
    angle_id: Optional[str] = None
    angle_name: str
    description: Optional[str] = ""
    template: Optional[str] = ""               # The actual outreach script / framework
    best_for: Optional[str] = ""               # What kinds of initiatives this works well for
    used_in: Optional[str] = ""                # Comma-separated initiative IDs
    effectiveness_notes: Optional[str] = ""


# ── ACTION ITEMS ──────────────────────────────────────────────────────────────

class ActionItemPayload(BaseModel):
    action_id: Optional[str] = None
    initiative_id: Optional[str] = ""          # "SPRINT" for standalone tasks
    sub_project_id: Optional[str] = ""
    stakeholder_id: Optional[str] = ""
    action_type: Optional[str] = ""            # Research / Outreach / Content / Logistics / Follow Up / Decision
    description: str
    status: Optional[str] = "Open"             # Open / In Progress / Waiting / Complete
    priority: Optional[str] = "Medium"
    due_date: Optional[str] = None             # ISO date string
    google_task_id: Optional[str] = ""         # For two-way Google Tasks sync
    google_task_list: Optional[str] = ""
    source: Optional[str] = "Manual"           # Manual / Brain Dump / Meeting Transcript / Phoebe
    phoebe_tracking: Optional[bool] = False
    completed_date: Optional[str] = None


class ActionItemStatusUpdate(BaseModel):
    status: str
    completed_date: Optional[str] = None
    google_task_id: Optional[str] = None


# ── CONTENT ───────────────────────────────────────────────────────────────────

class ContentPayload(BaseModel):
    content_id: Optional[str] = None           # auto-generated if omitted (e.g. C001)
    content_name: str
    content_type: Optional[str] = ""           # Article / Campaign Concept / Gifting Moment /
                                               # Sequence Variant / Data Drop / Collab Hook /
                                               # Case Study / Demo / Newsletter Issue / Event Recap
    venture: Optional[str] = ""               # ReRev Labs / Prismm / Black Tech Capital / Sekhmetic
    initiative_tags: Optional[str] = ""       # Comma-separated project IDs e.g. "P008, P017"
    status: Optional[str] = "Idea"            # Idea / Draft / In Review / Active / Archived
    activation_angle: Optional[str] = ""      # What this content is meant to do / who it's for
    asset_link: Optional[str] = ""            # Google Doc, Notion, Drive link
    approval_required: Optional[str] = "No"  # Yes / No
    prismm_sync: Optional[str] = ""          # Pending / Synced / Needs Update / blank for non-Prismm
    notes: Optional[str] = ""


class ContentStatusUpdate(BaseModel):
    status: str
    prismm_sync: Optional[str] = None


# ── FOLLOW-UPS ────────────────────────────────────────────────────────────────

class FollowUpPayload(BaseModel):
    follow_up_id: Optional[str] = None        # auto-generated if omitted
    contact_name: str
    contact_id: Optional[str] = ""            # FK to contacts table
    meeting_name: Optional[str] = ""          # Which meeting triggered this follow-up
    meeting_date: Optional[str] = None        # ISO date string
    next_action: Optional[str] = ""           # What needs to happen e.g. "Send deck", "Intro to Martha"
    next_action_date: Optional[str] = None    # ISO date string — when it should happen by
    venture: Optional[str] = ""               # Which venture this follow-up is under
    transcript_link: Optional[str] = ""       # Link to the meeting transcript Google Doc
    draft_link: Optional[str] = ""            # Link to the Gmail draft if one was created
    status: Optional[str] = "Open"            # Open / Done / Overdue / Cancelled
    completed_date: Optional[str] = None      # ISO date string — when it was marked Done
    notes: Optional[str] = ""


class FollowUpStatusUpdate(BaseModel):
    status: str
    completed_date: Optional[str] = None
