import os
import json
import asyncpg
from pgvector.asyncpg import register_vector

DATABASE_URL = os.environ["DATABASE_URL"]

async def _conn():
    conn = await asyncpg.connect(DATABASE_URL, ssl="require")
    await register_vector(conn)
    return conn

async def init_db():
    conn = await _conn()
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                contact_id TEXT PRIMARY KEY,
                profile JSONB NOT NULL,
                embedding vector(1024),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS contacts_embedding_idx
            ON contacts USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """)
    finally:
        await conn.close()

async def store_contact(contact_id: str, profile: dict, vector: list):
    conn = await _conn()
    try:
        import numpy as np
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

async def get_all_contacts():
    conn = await _conn()
    try:
        rows = await conn.fetch("SELECT contact_id, profile FROM contacts ORDER BY updated_at DESC")
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
            SELECT
                contact_id,
                profile,
                1 - (embedding <=> $1::vector) AS similarity
            FROM contacts
            WHERE contact_id != $2
            ORDER BY embedding <=> $1::vector
            LIMIT $3;
        """, embedding, contact_id, limit)
        return [
            {
                "contact_id": r["contact_id"],
                "similarity": round(float(r["similarity"]), 4),
                **json.loads(r["profile"])
            }
            for r in rows
        ]
    finally:
        await conn.close()
