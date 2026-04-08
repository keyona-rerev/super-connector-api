# Super Connector — Full Database Enrichment Handoff
Generated: 2026-04-07

## What This Is

We are enriching all 4,535 contacts in Railway with `what_i_can_offer` and `what_they_offer_me` fields. 97 contacts are already done (the Accelerator Operators bucket). 4,438 remain.

Work is divided into 15 chunks of 300 contacts each (chunk 15 has 238). Multiple Claude sessions can run concurrently on different chunks with no conflicts since each session writes to different contact IDs.

---

## Key Credentials

| Item | Value |
|---|---|
| SC API Key | sc_live_k3y_2026_scak |
| Railway Base URL | https://super-connector-api-production.up.railway.app |
| GitHub Org | keyona-rerev |
| GitHub Repo | super-connector-api |
| Chunk Tracker File | enrich_chunks.json (in the repo root) |

---

## Chunk Assignments

| Chunk | Contacts | Offset Range | Recommended Session |
|---|---|---|---|
| chunk_01 | 300 | offset 0–299 | Session A |
| chunk_02 | 300 | offset 300–599 | Session A |
| chunk_03 | 300 | offset 600–899 | Session A |
| chunk_04 | 300 | offset 900–1199 | Session A |
| chunk_05 | 300 | offset 1200–1499 | Session B |
| chunk_06 | 300 | offset 1500–1799 | Session B |
| chunk_07 | 300 | offset 1800–2099 | Session B |
| chunk_08 | 300 | offset 2100–2399 | Session B |
| chunk_09 | 300 | offset 2400–2699 | Session C |
| chunk_10 | 300 | offset 2700–2999 | Session C |
| chunk_11 | 300 | offset 3000–3299 | Session C |
| chunk_12 | 300 | offset 3300–3599 | Session C |
| chunk_13 | 300 | offset 3600–3899 | Session D |
| chunk_14 | 300 | offset 3900–4199 | Session D |
| chunk_15 | 238 | offset 4200–4437 | Session D |

---

## What to Tell Each Claude Session

Paste this block as your opening message, replacing SESSION_LETTER and CHUNK/OFFSET values:

---

**Session A opening message:**

> I need you to enrich contacts in my Super Connector CRM. You are Session A. Your job is chunks 1 through 4 (offsets 0 to 1199).
>
> Railway API: https://super-connector-api-production.up.railway.app
> API Key header: X-API-Key: sc_live_k3y_2026_scak
>
> Steps:
> 1. Call GET /contacts?limit=100&offset=0, then offset=100, 200, ... up to offset=1100. That gives you 1,200 contacts.
> 2. Skip any contact that already has what_i_can_offer populated.
> 3. For each unenriched contact, write what_i_can_offer, what_they_offer_me, and contact_type directly to Railway using PUT /contact/{contact_id}.
> 4. Work in batches of 5. Research the person and org based on their name, title, and organization. Write to Railway after each batch.
> 5. Do not use the Anthropic API. Do the research yourself using your own knowledge and web search.
>
> Keyona's context for value exchange framing:
> - ReRev Labs: AI education, consulting, automation
> - Prismm: digital vault for community banks and credit unions ($250M-$2B asset range)
> - Black Tech Capital (BTC): climate tech nano VC
> - DO GOOD X: AI accelerator
> - Super Connector: AI-powered relationship intelligence CRM (the product she is outreaching about)
> - She is based in Birmingham, AL, is a connector, and regularly makes introductions between founders, operators, and investors.
>
> Contact types to assign: founder, investor, operator, connector, academic, other
>
> If you hit a context limit before finishing, stop cleanly, tell me the last offset you completed, and I will start a new session from that point.

---

**Session B opening message:** Same as above but replace "Session A" with "Session B" and offsets 0–1199 with offsets 1200–2399.

**Session C opening message:** Same but Session C, offsets 2400–3599.

**Session D opening message:** Same but Session D, offsets 3600–4437.

---

## How Enrichment Works (What Each Session Does)

Each session pulls contacts from Railway, filters out already-enriched ones, then for each pending contact:

1. Researches the person's name, title, and organization using web search and its own knowledge
2. Generates two fields:
   - `what_i_can_offer`: What Keyona can specifically bring to this person (introductions, resources, deal flow, visibility). 2-3 sentences, concrete, grounded in her actual ventures.
   - `what_they_offer_me`: What this person brings to Keyona's network. 2-3 sentences.
3. Assigns `contact_type`: founder / investor / operator / connector / academic / other
4. Writes all three fields to Railway via PUT /contact/{contact_id}

The PUT endpoint requires the full contact object, so the session must GET the contact first, update the three fields, then PUT the full object back.

---

## Checking Progress

At any time, run this to see how many contacts still need enrichment:

```bash
curl -s -H "X-API-Key: sc_live_k3y_2026_scak" \
  "https://super-connector-api-production.up.railway.app/contacts?limit=1&offset=0"
```

To check enrichment coverage across a range, ask any Claude session to run:

```python
import requests
HEADERS = {"X-API-Key": "sc_live_k3y_2026_scak"}
BASE = "https://super-connector-api-production.up.railway.app"

contacts = []
for offset in range(0, 4600, 100):
    batch = requests.get(f"{BASE}/contacts?limit=100&offset={offset}", headers=HEADERS, timeout=20).json().get("data", [])
    if not batch: break
    contacts.extend(batch)

enriched = sum(1 for c in contacts if (c.get("what_i_can_offer") or "").strip())
print(f"Total: {len(contacts)}, Enriched: {enriched}, Remaining: {len(contacts) - enriched}")
```

---

## If a Session Dies Mid-Chunk

No data is lost. Every write that succeeded before the session died is already in Railway. Start a new session, tell it the last offset it got to, and have it continue from there. It will automatically skip already-enriched contacts.

---

## When All Sessions Are Done

Ask any Claude session to run the progress check above. If remaining = 0, enrichment is complete. Then proceed with:

1. Duplicate initiative cleanup (14 confirmed duplicates in INI-1775595xxx range)
2. setupAllTriggers() on Phoebe GAS script ID: 1UeO72LgmCgEhr534Aw2ouj7lHKFiXe0mbGSCaFjsf1bphf510SOnkV4e
3. Gmail filter for SC/VerificationReplies label

---

## What Was Already Done This Session (2026-04-07)

- Built and deployed background enrich-all endpoint on Railway (POST /bucket/{id}/enrich-all)
- Fully enriched all 97 contacts in the Accelerator Operators bucket (BKT-1775579749337)
- Pushed enrich_chunks.json to this repo as the master chunk tracker
- Railway API key has $0 balance — do NOT use the Railway enricher endpoint for this run. Claude sessions do the research directly.
