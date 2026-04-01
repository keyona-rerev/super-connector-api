import os
import json
import asyncpg
from pgvector.asyncpg import register_vector

DATABASE_URL = os.environ["DATABASE_URL"]

async def _conn():
    conn = await asyncpg.connect(DATABASE_URL, ssl="require")
    await register_vector(conn)
    return conn

# ── SCHEMA INIT ───────────────────────────────────────────────────────────────

async def init_db():
    conn = await _conn()
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        # Contacts (existing)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                contact_id TEXT PRIMARY KEY,
                profile JSONB NOT NULL,
                embedding vector(512),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS contacts_embedding_idx
            ON contacts USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """)

        # Initiatives
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS initiatives (
                initiative_id TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)

        # Sub-Projects
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sub_projects (
                sub_project_id TEXT PRIMARY KEY,
                initiative_id TEXT NOT NULL,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS sub_projects_initiative_idx
            ON sub_projects (initiative_id);
        """)

        # Stakeholders (junction: contacts <-> initiatives)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS stakeholders (
                stakeholder_id TEXT PRIMARY KEY,
                contact_id TEXT,
                initiative_id TEXT NOT NULL,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS stakeholders_initiative_idx
            ON stakeholders (initiative_id);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS stakeholders_contact_idx
            ON stakeholders (contact_id);
        """)

        # Activation Angles
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS activation_angles (
                angle_id TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)

        # Action Items
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS action_items (
                action_id TEXT PRIMARY KEY,
                initiative_id TEXT,
                stakeholder_id TEXT,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS action_items_initiative_idx
            ON action_items (initiative_id);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS action_items_stakeholder_idx
            ON action_items (stakeholder_id);
        """)

        # Content Registry — vectorized so assets are semantically searchable
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS content (
                content_id TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                embedding vector(512),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS content_embedding_idx
            ON content USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 10);
        """)

        # Follow-Ups — vectorized so follow-ups are semantically searchable
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS follow_ups (
                follow_up_id TEXT PRIMARY KEY,
                contact_id TEXT,
                data JSONB NOT NULL,
                embedding vector(512),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS follow_ups_contact_idx
            ON follow_ups (contact_id);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS follow_ups_embedding_idx
            ON follow_ups USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 10);
        """)

        # Events — panels, workshops, networking; NOT interview episodes (those are sub-projects)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS events_venture_idx
            ON events ((data->>'venture'));
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS events_type_idx
            ON events ((data->>'event_type'));
        """)

        # Event Guests — contacts linked to an event with a role + status
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS event_guests (
                guest_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                contact_id TEXT,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS event_guests_event_idx
            ON event_guests (event_id);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS event_guests_contact_idx
            ON event_guests (contact_id);
        """)

        # Buckets — user-defined contact groups
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS buckets (
                bucket_id TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)

        # Contact Buckets — many-to-many join: contacts <-> buckets
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contact_buckets (
                bucket_id TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (bucket_id, contact_id)
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS contact_buckets_contact_idx
            ON contact_buckets (contact_id);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS contact_buckets_bucket_idx
            ON contact_buckets (bucket_id);
        """)

    finally:
        await conn.close()

# ── CONTACTS ──────────────────────────────────────────────────────────────────

async def store_contact(contact_id: str, profile: dict, vector: list):
    import numpy as np
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO contacts (contact_id, profile, embedding, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (contact_id)
            DO UPDATE SET
                profile = EXCLUDED.profile,
                embedding = EXCLUDED.embedding,
                updated_at = NOW();
        """, contact_id, json.dumps(profile), np.array(vector))
    finally:
        await conn.close()

async def get_contact(contact_id: str):
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT profile FROM contacts WHERE contact_id = $1", contact_id
        )
        return json.loads(row["profile"]) if row else None
    finally:
        await conn.close()

async def get_all_contacts(limit: int = 50, offset: int = 0):
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT contact_id, profile FROM contacts ORDER BY updated_at DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [{"contact_id": r["contact_id"], **json.loads(r["profile"])} for r in rows]
    finally:
        await conn.close()

async def count_contacts():
    conn = await _conn()
    try:
        row = await conn.fetchrow("SELECT COUNT(*) AS n FROM contacts")
        return row["n"]
    finally:
        await conn.close()

async def delete_contact(contact_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM contacts WHERE contact_id = $1", contact_id)
    finally:
        await conn.close()

async def find_similar(contact_id: str, limit: int = 5):
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT embedding FROM contacts WHERE contact_id = $1", contact_id
        )
        if not row:
            return None
        embedding = row["embedding"]
        rows = await conn.fetch("""
            SELECT contact_id, profile,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM contacts
            WHERE contact_id != $2
            ORDER BY embedding <=> $1::vector
            LIMIT $3;
        """, embedding, contact_id, limit)
        return [
            {"contact_id": r["contact_id"], "similarity": round(float(r["similarity"]), 4),
             **json.loads(r["profile"])}
            for r in rows
        ]
    finally:
        await conn.close()

async def find_similar_by_vector(vector: list, limit: int = 10):
    import numpy as np
    conn = await _conn()
    try:
        rows = await conn.fetch("""
            SELECT contact_id, profile,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM contacts
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2;
        """, np.array(vector), limit)
        return [
            {"contact_id": r["contact_id"], "similarity": round(float(r["similarity"]), 4),
             **json.loads(r["profile"])}
            for r in rows
        ]
    finally:
        await conn.close()

# ── INITIATIVES ───────────────────────────────────────────────────────────────

async def upsert_initiative(initiative_id: str, data: dict):
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO initiatives (initiative_id, data, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (initiative_id)
            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW();
        """, initiative_id, json.dumps(data))
    finally:
        await conn.close()

async def get_initiative(initiative_id: str):
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT data FROM initiatives WHERE initiative_id = $1", initiative_id
        )
        return json.loads(row["data"]) if row else None
    finally:
        await conn.close()

async def get_all_initiatives():
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT initiative_id, data FROM initiatives ORDER BY updated_at DESC"
        )
        return [{"initiative_id": r["initiative_id"], **json.loads(r["data"])} for r in rows]
    finally:
        await conn.close()

async def delete_initiative(initiative_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM initiatives WHERE initiative_id = $1", initiative_id)
    finally:
        await conn.close()

# ── SUB-PROJECTS ──────────────────────────────────────────────────────────────

async def upsert_sub_project(sub_project_id: str, initiative_id: str, data: dict):
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO sub_projects (sub_project_id, initiative_id, data, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (sub_project_id)
            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW();
        """, sub_project_id, initiative_id, json.dumps(data))
    finally:
        await conn.close()

async def get_sub_projects_for_initiative(initiative_id: str):
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT sub_project_id, data FROM sub_projects WHERE initiative_id = $1 ORDER BY updated_at DESC",
            initiative_id
        )
        return [{"sub_project_id": r["sub_project_id"], **json.loads(r["data"])} for r in rows]
    finally:
        await conn.close()

async def delete_sub_project(sub_project_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM sub_projects WHERE sub_project_id = $1", sub_project_id)
    finally:
        await conn.close()

# ── STAKEHOLDERS ──────────────────────────────────────────────────────────────

async def upsert_stakeholder(stakeholder_id: str, contact_id: str, initiative_id: str, data: dict):
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO stakeholders (stakeholder_id, contact_id, initiative_id, data, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (stakeholder_id)
            DO UPDATE SET
                contact_id = EXCLUDED.contact_id,
                data = EXCLUDED.data,
                updated_at = NOW();
        """, stakeholder_id, contact_id or "", initiative_id, json.dumps(data))
    finally:
        await conn.close()

async def get_stakeholders_for_initiative(initiative_id: str):
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT stakeholder_id, contact_id, data FROM stakeholders WHERE initiative_id = $1 ORDER BY updated_at DESC",
            initiative_id
        )
        return [
            {"stakeholder_id": r["stakeholder_id"], "contact_id": r["contact_id"],
             **json.loads(r["data"])}
            for r in rows
        ]
    finally:
        await conn.close()

async def get_stakeholders_for_contact(contact_id: str):
    """Get all initiatives a contact is involved in — powers cross-initiative surfacing."""
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT stakeholder_id, initiative_id, data FROM stakeholders WHERE contact_id = $1",
            contact_id
        )
        return [
            {"stakeholder_id": r["stakeholder_id"], "initiative_id": r["initiative_id"],
             **json.loads(r["data"])}
            for r in rows
        ]
    finally:
        await conn.close()

async def delete_stakeholder(stakeholder_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM stakeholders WHERE stakeholder_id = $1", stakeholder_id)
    finally:
        await conn.close()

# ── ACTIVATION ANGLES ─────────────────────────────────────────────────────────

async def upsert_activation_angle(angle_id: str, data: dict):
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO activation_angles (angle_id, data, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (angle_id)
            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW();
        """, angle_id, json.dumps(data))
    finally:
        await conn.close()

async def get_all_activation_angles():
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT angle_id, data FROM activation_angles ORDER BY updated_at DESC"
        )
        return [{"angle_id": r["angle_id"], **json.loads(r["data"])} for r in rows]
    finally:
        await conn.close()

async def delete_activation_angle(angle_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM activation_angles WHERE angle_id = $1", angle_id)
    finally:
        await conn.close()

# ── ACTION ITEMS ──────────────────────────────────────────────────────────────

async def upsert_action_item(action_id: str, initiative_id: str, stakeholder_id: str, data: dict):
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO action_items (action_id, initiative_id, stakeholder_id, data, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (action_id)
            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW();
        """, action_id, initiative_id or "", stakeholder_id or "", json.dumps(data))
    finally:
        await conn.close()

async def get_action_items_for_initiative(initiative_id: str):
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT action_id, data FROM action_items WHERE initiative_id = $1 ORDER BY updated_at DESC",
            initiative_id
        )
        return [{"action_id": r["action_id"], **json.loads(r["data"])} for r in rows]
    finally:
        await conn.close()

async def get_open_action_items(due_before: str = None):
    """Used by Phoebe for check-ins and due date warnings."""
    conn = await _conn()
    try:
        if due_before:
            rows = await conn.fetch("""
                SELECT action_id, initiative_id, data FROM action_items
                WHERE data->>'status' != 'Complete'
                AND data->>'due_date' IS NOT NULL
                AND data->>'due_date' != ''
                AND data->>'due_date' <= $1
                ORDER BY data->>'due_date' ASC
            """, due_before)
        else:
            rows = await conn.fetch("""
                SELECT action_id, initiative_id, data FROM action_items
                WHERE data->>'status' != 'Complete'
                ORDER BY updated_at DESC
            """)
        return [
            {"action_id": r["action_id"], "initiative_id": r["initiative_id"],
             **json.loads(r["data"])}
            for r in rows
        ]
    finally:
        await conn.close()

async def get_action_item_by_google_task_id(google_task_id: str):
    """Two-way Google Tasks sync — look up by task ID."""
    conn = await _conn()
    try:
        row = await conn.fetchrow("""
            SELECT action_id, data FROM action_items
            WHERE data->>'google_task_id' = $1
        """, google_task_id)
        return {"action_id": row["action_id"], **json.loads(row["data"])} if row else None
    finally:
        await conn.close()

async def delete_action_item(action_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM action_items WHERE action_id = $1", action_id)
    finally:
        await conn.close()

# ── CONTENT ───────────────────────────────────────────────────────────────────

async def store_content(content_id: str, data: dict, vector: list):
    """Upsert a content asset with its embedding."""
    import numpy as np
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO content (content_id, data, embedding, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (content_id)
            DO UPDATE SET
                data = EXCLUDED.data,
                embedding = EXCLUDED.embedding,
                updated_at = NOW();
        """, content_id, json.dumps(data), np.array(vector))
    finally:
        await conn.close()

async def get_content(content_id: str):
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT data FROM content WHERE content_id = $1", content_id
        )
        return json.loads(row["data"]) if row else None
    finally:
        await conn.close()

async def get_all_content():
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT content_id, data FROM content ORDER BY updated_at DESC"
        )
        return [{"content_id": r["content_id"], **json.loads(r["data"])} for r in rows]
    finally:
        await conn.close()

async def search_content_by_vector(vector: list, limit: int = 10):
    """Semantic search across content assets — e.g. 'Prismm community bank article'."""
    import numpy as np
    conn = await _conn()
    try:
        rows = await conn.fetch("""
            SELECT content_id, data,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM content
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2;
        """, np.array(vector), limit)
        return [
            {"content_id": r["content_id"], "similarity": round(float(r["similarity"]), 4),
             **json.loads(r["data"])}
            for r in rows
        ]
    finally:
        await conn.close()

async def delete_content(content_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM content WHERE content_id = $1", content_id)
    finally:
        await conn.close()

# ── FOLLOW-UPS ────────────────────────────────────────────────────────────────

async def store_follow_up(follow_up_id: str, contact_id: str, data: dict, vector: list):
    """Upsert a follow-up with its embedding."""
    import numpy as np
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO follow_ups (follow_up_id, contact_id, data, embedding, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (follow_up_id)
            DO UPDATE SET
                contact_id = EXCLUDED.contact_id,
                data = EXCLUDED.data,
                embedding = EXCLUDED.embedding,
                updated_at = NOW();
        """, follow_up_id, contact_id or "", json.dumps(data), np.array(vector))
    finally:
        await conn.close()

async def get_follow_up(follow_up_id: str):
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT data FROM follow_ups WHERE follow_up_id = $1", follow_up_id
        )
        return json.loads(row["data"]) if row else None
    finally:
        await conn.close()

async def get_open_follow_ups():
    """All follow-ups with status = Open — used by Phoebe Monday scan."""
    conn = await _conn()
    try:
        rows = await conn.fetch("""
            SELECT follow_up_id, contact_id, data FROM follow_ups
            WHERE data->>'status' = 'Open'
            ORDER BY data->>'next_action_date' ASC NULLS LAST
        """)
        return [
            {"follow_up_id": r["follow_up_id"], "contact_id": r["contact_id"],
             **json.loads(r["data"])}
            for r in rows
        ]
    finally:
        await conn.close()

async def get_overdue_follow_ups(as_of_date: str):
    """Follow-ups where next_action_date has passed and status is still Open."""
    conn = await _conn()
    try:
        rows = await conn.fetch("""
            SELECT follow_up_id, contact_id, data FROM follow_ups
            WHERE data->>'status' = 'Open'
            AND data->>'next_action_date' IS NOT NULL
            AND data->>'next_action_date' != ''
            AND data->>'next_action_date' < $1
            ORDER BY data->>'next_action_date' ASC
        """, as_of_date)
        return [
            {"follow_up_id": r["follow_up_id"], "contact_id": r["contact_id"],
             **json.loads(r["data"])}
            for r in rows
        ]
    finally:
        await conn.close()

async def get_follow_ups_for_contact(contact_id: str):
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT follow_up_id, data FROM follow_ups WHERE contact_id = $1 ORDER BY updated_at DESC",
            contact_id
        )
        return [{"follow_up_id": r["follow_up_id"], **json.loads(r["data"])} for r in rows]
    finally:
        await conn.close()

async def search_follow_ups_by_vector(vector: list, limit: int = 10):
    """Semantic search — e.g. 'who do I owe a follow-up about climate tech?'"""
    import numpy as np
    conn = await _conn()
    try:
        rows = await conn.fetch("""
            SELECT follow_up_id, contact_id, data,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM follow_ups
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2;
        """, np.array(vector), limit)
        return [
            {"follow_up_id": r["follow_up_id"], "contact_id": r["contact_id"],
             "similarity": round(float(r["similarity"]), 4),
             **json.loads(r["data"])}
            for r in rows
        ]
    finally:
        await conn.close()

async def delete_follow_up(follow_up_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM follow_ups WHERE follow_up_id = $1", follow_up_id)
    finally:
        await conn.close()

# ── EVENTS ────────────────────────────────────────────────────────────────────

async def upsert_event(event_id: str, data: dict):
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO events (event_id, data, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (event_id)
            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW();
        """, event_id, json.dumps(data))
    finally:
        await conn.close()

async def get_event(event_id: str):
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT data FROM events WHERE event_id = $1", event_id
        )
        return json.loads(row["data"]) if row else None
    finally:
        await conn.close()

async def get_all_events(event_type: str = None, venture: str = None):
    """List all events, optionally filtered by type and/or venture."""
    conn = await _conn()
    try:
        if event_type and venture:
            rows = await conn.fetch("""
                SELECT event_id, data FROM events
                WHERE data->>'event_type' = $1 AND data->>'venture' = $2
                ORDER BY data->>'date' DESC NULLS LAST
            """, event_type, venture)
        elif event_type:
            rows = await conn.fetch("""
                SELECT event_id, data FROM events
                WHERE data->>'event_type' = $1
                ORDER BY data->>'date' DESC NULLS LAST
            """, event_type)
        elif venture:
            rows = await conn.fetch("""
                SELECT event_id, data FROM events
                WHERE data->>'venture' = $1
                ORDER BY data->>'date' DESC NULLS LAST
            """, venture)
        else:
            rows = await conn.fetch(
                "SELECT event_id, data FROM events ORDER BY data->>'date' DESC NULLS LAST"
            )
        return [{"event_id": r["event_id"], **json.loads(r["data"])} for r in rows]
    finally:
        await conn.close()

async def delete_event(event_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM events WHERE event_id = $1", event_id)
    finally:
        await conn.close()

# ── EVENT GUESTS ──────────────────────────────────────────────────────────────

async def upsert_event_guest(guest_id: str, event_id: str, contact_id: str, data: dict):
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO event_guests (guest_id, event_id, contact_id, data, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (guest_id)
            DO UPDATE SET
                contact_id = EXCLUDED.contact_id,
                data = EXCLUDED.data,
                updated_at = NOW();
        """, guest_id, event_id, contact_id or "", json.dumps(data))
    finally:
        await conn.close()

async def get_guests_for_event(event_id: str):
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT guest_id, contact_id, data FROM event_guests WHERE event_id = $1 ORDER BY updated_at ASC",
            event_id
        )
        return [
            {"guest_id": r["guest_id"], "contact_id": r["contact_id"],
             **json.loads(r["data"])}
            for r in rows
        ]
    finally:
        await conn.close()

async def delete_event_guest(guest_id: str):
    conn = await _conn()
    try:
        await conn.execute("DELETE FROM event_guests WHERE guest_id = $1", guest_id)
    finally:
        await conn.close()

# ── BUCKETS ───────────────────────────────────────────────────────────────────

async def upsert_bucket(bucket_id: str, data: dict):
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO buckets (bucket_id, data, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (bucket_id)
            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW();
        """, bucket_id, json.dumps(data))
    finally:
        await conn.close()

async def get_all_buckets():
    """Return all buckets with their member contact_ids."""
    conn = await _conn()
    try:
        rows = await conn.fetch(
            "SELECT bucket_id, data FROM buckets ORDER BY updated_at DESC"
        )
        buckets = []
        for r in rows:
            b = {"bucket_id": r["bucket_id"], **json.loads(r["data"])}
            members = await conn.fetch(
                "SELECT contact_id FROM contact_buckets WHERE bucket_id = $1", r["bucket_id"]
            )
            b["contact_ids"] = [m["contact_id"] for m in members]
            b["count"] = len(b["contact_ids"])
            buckets.append(b)
        return buckets
    finally:
        await conn.close()

async def get_bucket(bucket_id: str):
    conn = await _conn()
    try:
        row = await conn.fetchrow(
            "SELECT data FROM buckets WHERE bucket_id = $1", bucket_id
        )
        if not row:
            return None
        b = {"bucket_id": bucket_id, **json.loads(row["data"])}
        members = await conn.fetch(
            "SELECT contact_id FROM contact_buckets WHERE bucket_id = $1", bucket_id
        )
        b["contact_ids"] = [m["contact_id"] for m in members]
        b["count"] = len(b["contact_ids"])
        return b
    finally:
        await conn.close()

async def delete_bucket(bucket_id: str):
    conn = await _conn()
    try:
        # Remove all memberships first, then the bucket
        await conn.execute("DELETE FROM contact_buckets WHERE bucket_id = $1", bucket_id)
        await conn.execute("DELETE FROM buckets WHERE bucket_id = $1", bucket_id)
    finally:
        await conn.close()

async def add_contact_to_bucket(bucket_id: str, contact_id: str):
    conn = await _conn()
    try:
        await conn.execute("""
            INSERT INTO contact_buckets (bucket_id, contact_id)
            VALUES ($1, $2)
            ON CONFLICT (bucket_id, contact_id) DO NOTHING;
        """, bucket_id, contact_id)
    finally:
        await conn.close()

async def remove_contact_from_bucket(bucket_id: str, contact_id: str):
    conn = await _conn()
    try:
        await conn.execute(
            "DELETE FROM contact_buckets WHERE bucket_id = $1 AND contact_id = $2",
            bucket_id, contact_id
        )
    finally:
        await conn.close()

async def get_buckets_for_contact(contact_id: str):
    """All buckets a contact belongs to."""
    conn = await _conn()
    try:
        rows = await conn.fetch("""
            SELECT b.bucket_id, b.data
            FROM buckets b
            JOIN contact_buckets cb ON b.bucket_id = cb.bucket_id
            WHERE cb.contact_id = $1
            ORDER BY b.updated_at DESC
        """, contact_id)
        return [{"bucket_id": r["bucket_id"], **json.loads(r["data"])} for r in rows]
    finally:
        await conn.close()

async def get_contacts_in_bucket(bucket_id: str):
    """Full contact profiles for everyone in a bucket."""
    conn = await _conn()
    try:
        rows = await conn.fetch("""
            SELECT c.contact_id, c.profile
            FROM contacts c
            JOIN contact_buckets cb ON c.contact_id = cb.contact_id
            WHERE cb.bucket_id = $1
            ORDER BY c.updated_at DESC
        """, bucket_id)
        return [{"contact_id": r["contact_id"], **json.loads(r["profile"])} for r in rows]
    finally:
        await conn.close()
