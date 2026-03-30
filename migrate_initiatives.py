"""
One-time migration: pushes all 26 initiatives from Google Sheets into Railway.
Run with: python migrate_initiatives.py
Requires SC_API_KEY env var set.
"""
import httpx
import os
import time

API_BASE = "https://super-connector-api-production.up.railway.app"
API_KEY  = os.environ["SC_API_KEY"]

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}

# Status mapping — Sheet uses some non-standard values
STATUS_MAP = {
    "Active":      "Active",
    "Planning":    "Planning",
    "Paused":      "Paused",
    "Complete":    "Complete",
    "Blocked":     "Blocked",
    "Monitor":     "Planning",   # closest equivalent
    "In Progress": "Active",
    "Brain Dump":  "Brain Dump",
}

INITIATIVES = [
    {"initiative_id":"P001","initiative_name":"Prismm GTM Strategy Reference","venture":"Prismm","status":"Active","priority":"High","goal":"Prismm has a documented, accessible GTM strategy that stays current and can be referenced anytime","notes":"Martha completed 42-tactic exercise. Strategy has evolved — Bessemer framework applied, ABM motion defined, channels mapped (LinkedIn, earned media, conferences, email nurture). Needs to be consolidated into a single living reference.","phoebe_cadence":"Weekly","timeline":"Q2 2026"},
    {"initiative_id":"P003","initiative_name":"DO Good X Content Strategy","venture":"Prismm","status":"Paused","priority":"Low","goal":"Resume content-as-distribution partnership with DoGoodX if contract reinstated","notes":"Contract cancelled due to low signups. Martha to provide any updates. Official non-priority — do not spend time here until reactivated.","phoebe_cadence":"Monthly","timeline":"TBD"},
    {"initiative_id":"P004","initiative_name":"SOC 2 Compliance","venture":"Prismm","status":"Complete","priority":"High","goal":"Prismm systems meet SOC 2 Type II compliance standards","notes":"Vanta client installed, policies reviewed, device compliant. Complete.","phoebe_cadence":"None","timeline":"Q4 2025"},
    {"initiative_id":"P005","initiative_name":"Fundraising / Investment Raise","venture":"Prismm","status":"Planning","priority":"High","goal":"Prismm closes its seed round with a committed lead investor","notes":"Martha-owned. 'The money agenda' resource was to be shared. No action required from Keyona — monitor only.","phoebe_cadence":"Monthly","timeline":"TBD"},
    {"initiative_id":"P006","initiative_name":"Sales Targeting — Top 20 Banks","venture":"Prismm","status":"Active","priority":"High","goal":"Prismm has a prioritized, researched list of 20 target banks with contact-level intel feeding the ABM motion","notes":"Martha partially delivered. Blocking P014 (ABM) and P018 (990s Research). Needs immediate triage — should be complete by end of March.","phoebe_cadence":"Every 2-3 days","timeline":"Q1 2026"},
    {"initiative_id":"P007","initiative_name":"Prismm Advisory Council","venture":"Prismm","status":"Blocked","priority":"High","goal":"Prismm has 5 advisors recruited across key role archetypes","notes":"Martha approved 11 role archetypes, wants max 5 advisors, needs deep regulatory/FI compliance expert. Blocked on compensation model — no equity for advisory. Need to propose alternatives: access, visibility, title, intros.","phoebe_cadence":"Weekly","timeline":"Q2 2026"},
    {"initiative_id":"P008","initiative_name":"Middle-of-Funnel Buildout","venture":"Prismm","status":"Active","priority":"High","goal":"Prismm has a live content engine — website, LinkedIn, and email all moving buyers from awareness to evaluation","notes":"Bessemer framework applied, content capsule planned, website hero identified as wrong. Needs audit of what exists vs what still needed.","phoebe_cadence":"Weekly","timeline":"Q2 2026"},
    {"initiative_id":"P009","initiative_name":"Events Strategy","venture":"Prismm","status":"Active","priority":"Medium","goal":"Prismm has a systematized events playbook with automated budget alerts and a maintained 2026 calendar","notes":"7 conferences mapped with happy hour playbooks and cost estimates. 90-day notification automation for Martha not yet built.","phoebe_cadence":"Every 2-3 days","timeline":"Q1-Q2 2026"},
    {"initiative_id":"P010","initiative_name":"Google Ecosystem Systems Build","venture":"Prismm","status":"Complete","priority":"Medium","goal":"Prismm internal ops and GTM systems are built on Google ecosystem","notes":"Delivered: Ops Hub, ToFu Command, MoFu Command, Relationship Manager spec, Compliance Manager. Project retired.","phoebe_cadence":"None","timeline":"Q4 2025"},
    {"initiative_id":"P011","initiative_name":"Partnerships Ecosystem","venture":"Prismm","status":"Planning","priority":"Medium","goal":"Prismm has a documented partner ecosystem with outreach plan covering NABA, Urban League, Family Offices","notes":"Martha to create wish list of preferred brand partners. No evidence this was ever delivered.","phoebe_cadence":"Monthly","timeline":"Q2 2026"},
    {"initiative_id":"P012","initiative_name":"Product Onboarding + Storylane","venture":"Prismm","status":"Blocked","priority":"Medium","goal":"Prismm has a complete approved product demo and onboarding sequence live","notes":"Logged into Storylane, built ABA demo — Martha pulled it as proprietary. GitHub site access still pending from Martha.","phoebe_cadence":"Weekly","timeline":"Q2 2026"},
    {"initiative_id":"P014","initiative_name":"ABM Strategy — Banking Executives","venture":"Prismm","status":"Active","priority":"High","goal":"Prismm has a running ABM motion with personalized sequences for named banking executive targets","notes":"Three-app GTM OS architected. Blocked until P006 bank list is finalized. Pipedrive or Attio as CRM layer.","phoebe_cadence":"Every 2-3 days","timeline":"Q2 2026"},
    {"initiative_id":"P015","initiative_name":"Influencer and Gifting Strategy","venture":"Prismm","status":"Paused","priority":"Low","goal":"Prismm has an active influencer and gifting program driving brand awareness","notes":"Concept only. Artists like Pink Beard mentioned. No movement.","phoebe_cadence":"Monthly","timeline":"Q3 2026"},
    {"initiative_id":"P016","initiative_name":"B2C Mini-Course","venture":"Prismm","status":"Paused","priority":"Medium","goal":"Prismm has a live B2C mini-course on end-of-life readiness driving consumer confidence and CTA conversion","notes":"Was waiting on website updates as of late 2025. Ties to Continuux B2C messaging.","phoebe_cadence":"Monthly","timeline":"Q3 2026"},
    {"initiative_id":"P017","initiative_name":"Kaleidoscope Campaign","venture":"Prismm","status":"Active","priority":"Medium","goal":"Kaleidoscope Campaign is executed with a defined gifting moment, distribution list, and measurable outcome","notes":"Martha approved concept (brain health + financial health gift campaign for older bank customers). Needs a full arc: beginning, middle, end.","phoebe_cadence":"Weekly","timeline":"Q3 2026"},
    {"initiative_id":"P018","initiative_name":"Banking DB and 990s Research","venture":"Prismm","status":"Active","priority":"High","goal":"Prismm has a complete database of target banks with board-level contacts sourced from 990 research","notes":"Flagged as not started as far back as Feb 2026. Was due Dec 2025. Directly feeds ABM motion. Claude can do this research autonomously.","phoebe_cadence":"Daily","timeline":"Q1 2026"},
    {"initiative_id":"P019","initiative_name":"Case Studies — Renaissance","venture":"Prismm","status":"Planning","priority":"Medium","goal":"Prismm has completed case studies from Renaissance partnership ready for BOFU distribution","notes":"Blocked on Renaissance data being available.","phoebe_cadence":"Monthly","timeline":"Q2 2026"},
    {"initiative_id":"P020","initiative_name":"CRM Transition — Pipedrive","venture":"Prismm","status":"Active","priority":"Medium","goal":"Prismm is operating on a live CRM with migrated contacts and working sales workflows","notes":"Was blocked on SOC 2 — SOC 2 is now complete. Needs Pipedrive vs Attio platform decision first.","phoebe_cadence":"Weekly","timeline":"Q2 2026"},
    {"initiative_id":"P021","initiative_name":"Prismm ABA Submission","venture":"Prismm","status":"Complete","priority":"High","goal":"Prismm demo submitted to American Bankers Association","notes":"Successfully submitted. Complete.","phoebe_cadence":"None","timeline":"Q4 2025"},
    {"initiative_id":"PN001","initiative_name":"New York Initiative Execution","venture":"Prismm","status":"Active","priority":"Medium","goal":"Prismm NYC pipeline is fully actioned and logged","notes":"Updated contact list received. School contract work ongoing. Martha-Neonta Williams connection to be facilitated.","phoebe_cadence":"Every 2-3 days","timeline":"Q1 2026"},
    {"initiative_id":"INI-001","initiative_name":"BTC Climate Tech Exit Lab","venture":"Black Tech Capital","status":"Active","priority":"High","goal":"Build a comprehensive interview series and collective intelligence repository on climate tech exits","core_question":"How do we systematize climate tech exit learnings for founders?","brain_dump":"Monthly interviews with climate tech founders who have exited","notes":"Foundational project for BTC. Involves monthly interviews, advisory committee formation, sponsorship pipeline. SXSW mentor connection pending.","phoebe_cadence":"Weekly","brand":"Black Tech Capital","distribution":"Interview series, newsletter, report","format":"Podcast / written interviews","timeline":"Q2 2026"},
    {"initiative_id":"INI-002","initiative_name":"ReRev Automation Sales to Marketing Agencies","venture":"ReRev Labs","status":"Planning","priority":"High","goal":"Close 3-5 marketing agencies as customers/feedback partners for ReRev's automation training series","core_question":"How do we prove ReRev automation training value to agencies?","brain_dump":"Cold email + free value exchange offering $500 automation audit to marketing agencies","notes":"Free value exchange activation angle: cold outreach with free automation install worth $500 to get feedback and testimonials.","phoebe_cadence":"Weekly","brand":"ReRev Labs","distribution":"LinkedIn, email","format":"Email sequence + case studies","timeline":"Q2 2026"},
    {"initiative_id":"INI-003","initiative_name":"BTC Compliance Calendar Optimization","venture":"Black Tech Capital","status":"Planning","priority":"Medium","goal":"BTC has an optimized, automated compliance calendar reducing manual tracking and compliance risk","core_question":"What are the key compliance deadlines for climate tech fund operations?","brain_dump":"Regulatory and operational calendar optimization","notes":"Operational excellence initiative. Involves 10K filing dates, LP reporting cycles, investment documentation deadlines.","phoebe_cadence":"Biweekly","brand":"Black Tech Capital","distribution":"Internal operations","format":"Automation / calendar system","timeline":"Q2 2026"},
    {"initiative_id":"INI-004","initiative_name":"ReRev Newsletter Launch","venture":"ReRev Labs","status":"Planning","priority":"Medium","goal":"ReRev has a weekly newsletter establishing thought leadership and building direct audience","core_question":"How do we build ReRev's direct audience for future product launches?","brain_dump":"Weekly thought leadership and audience building through email","notes":"Content distribution hub for AI education, consulting insights, and automation case studies.","phoebe_cadence":"Weekly","brand":"ReRev Labs","distribution":"Email newsletter","format":"Newsletter / written","timeline":"Q2 2026"},
    {"initiative_id":"INI-005","initiative_name":"Sekhmetic Website Launch","venture":"Sekhmetic","status":"Active","priority":"High","goal":"Sekhmetic DJ brand has a live website showcasing services, mixes, booking info, and brand story","core_question":"How do we showcase Sekhmetic services and enable bookings?","brain_dump":"DJ brand website showcasing services and booking","notes":"Sprint-level initiative. Website 80% complete as of late March. Use case section is the remaining blocker.","phoebe_cadence":"Every 2-3 days","brand":"Sekhmetic","distribution":"Website","format":"Website","timeline":"Q1 2026"},
    {"initiative_id":"INI-006","initiative_name":"Sekhmetic Texting Service Setup","venture":"Sekhmetic","status":"Planning","priority":"Medium","goal":"Sekhmetic fans can opt in to text updates for new mixes, event announcements, and booking inquiries","core_question":"How do we maintain direct fan contact and engagement?","brain_dump":"SMS texting service for fan engagement and event updates","notes":"Lightweight engagement channel. Could use Twilio or similar. Complements website launch.","phoebe_cadence":"Weekly","brand":"Sekhmetic","distribution":"SMS / texting","format":"Automation / SMS","timeline":"Q2 2026"},
]

def main():
    print(f"Migrating {len(INITIATIVES)} initiatives to Railway...\n")
    success = 0
    failed  = 0

    with httpx.Client(timeout=30) as client:
        for ini in INITIATIVES:
            # Normalize status
            ini["status"] = STATUS_MAP.get(ini.get("status",""), ini.get("status","Brain Dump"))

            try:
                r = client.post(f"{API_BASE}/initiative", headers=HEADERS, json=ini)
                r.raise_for_status()
                print(f"  ✓ {ini['initiative_id']} — {ini['initiative_name']}")
                success += 1
            except Exception as e:
                print(f"  ✗ {ini['initiative_id']} — {ini['initiative_name']}: {e}")
                failed += 1

            time.sleep(0.1)  # be gentle

    print(f"\nDone. {success} succeeded, {failed} failed.")

if __name__ == "__main__":
    main()
