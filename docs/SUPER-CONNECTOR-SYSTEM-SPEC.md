# SUPER CONNECTOR SYSTEM SPEC
## Relationship Intelligence + Initiative Management + Proactive AI Agent (Phoebe)

---

## 0. HANDOFF CONTEXT

**Who is this for:** Keyona Meeks — founder operating across multiple ventures simultaneously. This spec was designed through an extended simulation and brain-dump session where Keyona walked through real initiatives to stress-test the data model.

**Ventures:**
- **ReRev Labs** — AI education, consulting, automation sales to marketing agencies, curriculum development
- **Prismm** — White-label digital vault platform, B2B sales to community banks and credit unions ($250M-$2B asset tier). Keyona is a co-founder. This is client work with its own GTM tools (T010, T011, T012, T016, T019).
- **Black Tech Capital (BTC)** — Climate tech nano VC fund. Key IP: Climate Tech Exit Lab interview series, compliance calendar optimization.
- **Sekhmetic** — Keyona's DJ brand. Website launch and texting service setup are active sprint tasks.

**Technical environment:**
- Windows machine, username `Owner`
- Google Workspace (Sheets, Calendar, Gmail, Tasks, Drive, Apps Script)
- Railway for backend services (FastAPI + pgvector for vector search)
- GitHub: `keyona-rerev` org
- Apollo.io connected as MCP in Claude.ai
- Claude.ai Pro plan with MCP connectors (Google Sheets, Tasks, Calendar, Gmail, GitHub, Apollo, Canva, Notion, tldraw)
- Anthropic API key available for GAS scripts (stored in Script Properties)

**Key design principle from Keyona:** "Information given is information captured is information referenced." The system must never ask the same question twice without referencing what was previously said. No hallucinated data — every field comes from a real source or stays blank.

**Phoebe check-in cadence:** Monday + Thursday + 3 business days before any due date.

**Google Tasks is a first-class data source** — T018 (Post-Meeting Intelligence Engine) already creates todos there after processing meeting transcripts. Phoebe must read from Google Tasks, not just write to it.

**Tool Registry:** Every tool Keyona has built is tracked in Sheet ID `1ol8Yvpe454T4yHpEgy8PFjOAJvfyUDrKesgD_wM7m4o` (tab: Registry). Check it before building anything new. Currently 20 tools (T001-T020).

---

## 1. WHAT THIS IS

The Super Connector is not a CRM. It's a system that fuses relationship intelligence with initiative management, powered by an AI agent called Phoebe who proactively manages Keyona's priorities.

**The core loop:**
1. Keyona brain-dumps (voice-to-text, conversation, meeting transcript)
2. The system captures and structures the dump into initiatives, sub-projects, stakeholders, activation angles, and action items
3. Phoebe monitors priorities, sends proactive check-ins, surfaces cross-initiative stakeholder overlaps, and nags about things that matter
4. Information given = information captured = information referenced. Nothing gets asked twice without reason.

**The system serves three ventures + personal:**
- ReRev Labs (AI education, consulting, automation sales)
- Prismm (digital vault platform for financial institutions)
- Black Tech Capital (climate tech nano VC fund)
- Personal / Sekhmetic (DJ brand)

---

## 2. DATA MODEL — SIX CORE ENTITIES

### Entity 1: Initiatives
The big containers. Each has a venture, a goal, sub-projects, stakeholders, and a priority in the queue.

**Evolves the existing Initiatives tab** (Sheet ID: `1Mvo3qP0KM1PgYl4rx8W9Dh2i78_9FmzHl5u-BHda8B0`)

| Column | Type | Description |
|--------|------|-------------|
| Initiative ID | Text | Auto-generated (INI-001, INI-002...) |
| Initiative Name | Text | e.g. "BTC Climate Tech Exit Lab" |
| Venture | Dropdown | ReRev / Prismm / BTC / Personal / Sekhmetic |
| Goal | Text | What success looks like |
| Core Question | Text | The one question this initiative answers (optional) |
| Status | Dropdown | Brain Dump / Planning / Active / Paused / Complete |
| Priority | Dropdown | Critical / High / Medium / Low / Parked |
| Timeline | Text | Key dates and milestones |
| Brand | Text | Which brand this ships under |
| Distribution | Text | Newsletter, LinkedIn, website, etc. |
| Format | Text | Podcast, written, video, animation, etc. |
| Budget | Text | Amount or "Zero" |
| Brain Dump | Text | The raw unstructured thinking that started this |
| Phoebe Cadence | Dropdown | Daily / Every 2-3 days / Weekly / Biweekly / Monthly / None |
| Last Phoebe Check-in | Date | When Phoebe last asked about this |
| Last Updated | Date | |
| Created Date | Date | |

**Examples from this conversation:**
- BTC Climate Tech Exit Lab (Active, High, Weekly cadence)
- ReRev Automation Sales to Marketing Agencies (Planning, High, Weekly)
- BTC Compliance Calendar Optimization (Planning, Medium, Biweekly)
- ReRev Newsletter Launch (Planning, Medium, Weekly)
- Sekhmetic Website Launch (Active, High, Every 2-3 days — sprint task)
- Sekhmetic Texting Service Setup (Planning, Medium, Weekly — sprint task)

### Entity 2: Sub-Projects
Nested work streams within an initiative. Each has its own status, stakeholders, and action items.

**New tab: Sub-Projects** (add to the Initiatives sheet or create dedicated Super Connector sheet)

| Column | Type | Description |
|--------|------|-------------|
| Sub-Project ID | Text | Auto-generated (SUB-001...) |
| Initiative ID | Text | Foreign key to Initiatives |
| Sub-Project Name | Text | e.g. "Monthly Interview Series" |
| Description | Text | What this work stream accomplishes |
| Status | Dropdown | Not Started / In Progress / Blocked / Complete |
| Priority | Dropdown | Critical / High / Medium / Low |
| Dependencies | Text | What needs to happen first |
| Owner | Text | Usually Keyona, but could be delegated |
| Notes | Text | |

**Example: BTC Climate Exit Lab sub-projects:**
- Monthly interview series (founders who've exited)
- Collective intelligence gathering (big-picture narrative)
- Individual deep-dive interviews
- Advisory committee formation
- Sponsorship pipeline (info interviews → decision → sales)

### Entity 3: Stakeholders
People tagged to initiatives with a specific role. NOT a flat contact list. The same person can be a stakeholder in multiple initiatives with different roles.

**New tab: Stakeholders** — this is the bridge between contacts and initiatives

| Column | Type | Description |
|--------|------|-------------|
| Stakeholder ID | Text | Auto-generated |
| Contact ID | Text | Foreign key to Contacts tab (Super Connector CRM) |
| Full Name | Text | Denormalized for readability |
| Initiative ID | Text | Foreign key to Initiatives |
| Sub-Project ID | Text | Optional — if tied to a specific sub-project |
| Role | Dropdown | Interview Subject / Advisor / Committee / Sponsor Prospect / Customer / Collaborator / Warm Path / Perspective Only |
| Action Needed | Dropdown | Outreach / Interview / Follow Up / Consider Perspective / None Yet |
| Engagement Status | Dropdown | Not Contacted / Contacted / Scheduled / Active / Complete / Declined |
| Notes | Text | Context specific to this person's role in this initiative |
| Added Date | Date | |

**Key design point:** "Perspective Only" means Keyona doesn't need to reach out to them, but needs to consider their viewpoint when making decisions for this initiative. This distinction matters — not every stakeholder requires action.

**Cross-initiative surfacing:** When Phoebe detects that a stakeholder appears in multiple initiatives, she flags this. "You're meeting with [Name] for the Climate Exit Lab interview — they're also relevant to your Compliance Calendar initiative. Want to add 5 minutes on IR cadence?"

### Entity 4: Activation Angles
Reusable approach templates that can apply across initiatives. These are the creative strategies — cold email + free value, interview series, sponsorship info call, guerrilla marketing, network activation, etc.

**New tab: Activation Angles**

| Column | Type | Description |
|--------|------|-------------|
| Angle ID | Text | Auto-generated |
| Angle Name | Text | e.g. "Free Value Exchange Cold Email" |
| Description | Text | How this approach works |
| Template | Text | The actual outreach template / script / framework |
| Best For | Text | What kinds of initiatives this works well for |
| Used In | Text | Comma-separated Initiative IDs where this has been applied |
| Effectiveness Notes | Text | What worked, what didn't |
| Created Date | Date | |

**Examples from this conversation:**
- "Free Automation Install for Feedback" — cold email marketing agencies offering a free $500 automation install in exchange for feedback on the series
- "Interview Series with Hindsight" — reach out to experienced practitioners asking for their hindsight on a specific topic
- "Sponsorship Informational" — early info-gathering calls with potential sponsors to understand their goals before pitching
- "Committee Formation" — assemble a small advisory group for credibility and fact-checking

### Entity 5: Action Items
Todos, research tasks, outreach tasks, content tasks. Tied to sub-projects and optionally to stakeholders.

**Two-way sync with Google Tasks** (T004 — Tasks MCP is already active)

Google Tasks is a critical part of this system because T018 (Post-Meeting Intelligence Engine) already creates todos there after every meeting. Phoebe needs to read from Google Tasks as a source of truth, not just write to it.

**The sync logic:**
- T018 creates todos in Google Tasks after processing meeting transcripts → Phoebe reads these and matches them to active initiatives/stakeholders if possible
- When a new action item is created in the Action Items tab, it gets pushed to the appropriate Google Tasks list
- When Keyona completes a task in Google Tasks, the Action Items tab gets updated (via periodic GAS sync)
- Phoebe's Monday and Thursday check-ins pull from BOTH the Action Items tab and Google Tasks to give a unified view
- Due date warnings scan both sources

| Column | Type | Description |
|--------|------|-------------|
| Action ID | Text | Auto-generated |
| Initiative ID | Text | Foreign key |
| Sub-Project ID | Text | Optional foreign key |
| Stakeholder ID | Text | Optional — if this action involves a specific person |
| Action Type | Dropdown | Research / Outreach / Content / Logistics / Follow Up / Decision |
| Description | Text | What needs to be done |
| Status | Dropdown | Open / In Progress / Waiting / Complete |
| Priority | Dropdown | Critical / High / Medium / Low |
| Due Date | Date | Optional |
| Google Task ID | Text | If synced to Google Tasks, the task ID for two-way updates |
| Google Task List | Text | Which Google Tasks list this lives in |
| Source | Dropdown | Manual / Brain Dump / Meeting Transcript / Phoebe |
| Phoebe Tracking | Boolean | Should Phoebe nag about this? |
| Completed Date | Date | |

**Google Tasks as the lightweight capture layer:** Sometimes Keyona doesn't need the full initiative → sub-project → action item pipeline. She just needs a todo. Google Tasks handles that. But Phoebe should still be aware of those tasks and surface them in check-ins, especially if they have due dates.

### Entity 6: Sprint Tasks
Standalone things that need to get done but don't warrant full initiative architecture. Quick wins, setup tasks, one-offs.

**Can live on the Action Items tab** with Initiative ID = "SPRINT" and a simplified view. Or a dedicated Sprint Tasks tab.

| Column | Type | Description |
|--------|------|-------------|
| Sprint ID | Text | Auto-generated |
| Task Name | Text | e.g. "Launch Sekhmetic website" |
| Venture | Dropdown | |
| Status | Dropdown | Not Started / In Progress / Done |
| Steps | Text | 2-5 steps max |
| Due Date | Date | |
| Priority | Dropdown | |

---

## 3. PHOEBE — THE PROACTIVE AI AGENT

### What Phoebe Is
A GAS-powered agent that autonomously reaches out to Keyona via email based on initiative priorities, calendar context, and system state. Phoebe is NOT reactive — she doesn't wait to be asked. She monitors and initiates.

### Phoebe's Core Behaviors

**Monday + Thursday Priority Check-ins (twice weekly)**
Phoebe emails Keyona twice a week:

Monday check-in (start of week):
- Top 3 highest-priority initiatives and their current status
- For each: "What's the status? What's blocking you?" — specific to what was last reported
- Any overdue action items (pulled from both Action Items tab AND Google Tasks via T004)
- Upcoming calendar meetings in the next 2 weeks that overlap with initiative stakeholders

Thursday check-in (mid-week pulse):
- Progress update on whatever Keyona reported Monday — "You said X was the priority this week. How's it going?"
- Any new action items created by T018 (post-meeting engine) since Monday
- Anything due Friday or early next week that needs attention

Keyona replies by email (or voice-to-text → email). Phoebe processes the reply via Claude API, updates statuses, creates new action items, and logs the check-in.

**Due Date Early Warning (3 business days before)**
When any action item or sprint task has a due date, Phoebe sends a heads-up email 3 business days before:
- "[Task] is due on [Date]. Current status: [Status]. What needs to happen to close this out?"
- If the task is tied to a stakeholder: "This involves [Name] — have you heard back from them?"
- Scans both the Action Items tab AND Google Tasks (via T004) for items with due dates.
- Does NOT duplicate — if a task exists in both Google Tasks and the Action Items tab, Phoebe references it once with both contexts.

**Pre-Meeting Briefing (triggered by calendar)**
When Phoebe detects a meeting on Google Calendar:
1. Look up the attendee(s) in the Contacts tab
2. Check if they appear in any Stakeholder tab entries
3. If yes: email Keyona a briefing — "You're meeting [Name] tomorrow. They're a stakeholder in [Initiative A] as [Role] and [Initiative B] as [Role]. Here's what you discussed last time [from