import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ["DATABASE_URL"]

def _conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    """Create the contacts table with pgvector column if it doesn't exist."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    contact_id TEXT PRIMARY KEY,
                    profile JSONB NOT NULL,
                    embedding vector(1024),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS contacts_embedding_idx
                ON contacts USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            """)
        conn.commit()

def store_contact(contact_id: str, profile: dict, vector: list):
    """Insert or update a contact with its embedding."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO contacts (contact_id, profile, embedding, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (contact_id)
                DO UPDATE SET
                    profile = EXCLUDED.profile,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW();
            """, (contact_id, json.dumps(profile), vector))
        conn.commit()

def get_contact(contact_id: str) -> dict | None:
    """Retrieve a single contact's profile by ID."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT profile FROM contacts WHERE contact_id = %s",
                (contact_id,)
            )
            row = cur.fetchone()
            return dict(row["profile"]) if row else None

def get_all_contacts() -> list[dict]:
    """Retrieve all contact profiles (no vectors)."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT contact_id, profile FROM contacts ORDER BY updated_at DESC")
            return [{"contact_id": r["contact_id"], **dict(r["profile"])} for r in cur.fetchall()]

def delete_contact(contact_id: str):
    """Remove a contact from the vector DB."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM contacts WHERE contact_id = %s", (contact_id,))
        conn.commit()

def find_similar(contact_id: str, limit: int = 5) -> list[dict] | None:
    """Find the most semantically similar contacts using cosine distance."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get the source contact's embedding
            cur.execute(
                "SELECT embedding FROM contacts WHERE contact_id = %s",
                (contact_id,)
            )
            row = cur.fetchone()
            if not row:
                return None

            embedding = row["embedding"]

            # Find closest neighbours, excluding the source contact itself
            cur.execute("""
                SELECT
                    contact_id,
                    profile,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM contacts
                WHERE contact_id != %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """, (embedding, contact_id, embedding, limit))

            return [
                {
                    "contact_id": r["contact_id"],
                    "similarity": round(float(r["similarity"]), 4),
                    **dict(r["profile"])
                }
                for r in cur.fetchall()
            ]
