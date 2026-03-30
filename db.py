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
