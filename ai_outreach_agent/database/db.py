"""
database/db.py
==============
PostgreSQL connection pool and all database helper functions.
All agents import from this module — nothing else touches the DB directly.
"""

import json
import os
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2 import pool as pgpool
from psycopg2.extras import RealDictCursor
from ai_outreach_agent.utils import load_env
from loguru import logger

load_env()

# ---------------------------------------------------------------------------
# Connection pool (created once at module import time)
# ---------------------------------------------------------------------------
_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/outreach_db")

try:
    _pool = pgpool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=_DATABASE_URL)
    logger.info("PostgreSQL connection pool initialised.")
except Exception as exc:
    logger.error(f"Failed to initialise DB pool: {exc}")
    _pool = None  # agents should check and raise early


@contextmanager
def get_connection():
    """Context manager that yields a psycopg2 connection from the pool."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialised. Check DATABASE_URL.")
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def apply_schema(schema_path: str = None) -> None:
    """Execute schema.sql if not already applied (idempotent due to IF NOT EXISTS)."""
    if schema_path is None:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r") as f:
        sql = f.read()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    logger.info("Schema applied successfully.")


# ---------------------------------------------------------------------------
# Company helpers
# ---------------------------------------------------------------------------

def insert_company(data: Dict[str, Any]) -> Optional[int]:
    """
    Insert a company record. On website conflict, skip silently.
    Returns the row id or None if skipped.
    """
    sql = """
        INSERT INTO companies
            (company_name, website, description, tech_stack,
             contact_email, linkedin, location, source)
        VALUES
            (%(company_name)s, %(website)s, %(description)s,
             %(tech_stack)s::JSONB, %(contact_email)s,
             %(linkedin)s, %(location)s, %(source)s)
        ON CONFLICT (website) DO NOTHING
        RETURNING id;
    """
    data.setdefault("source", "unknown")
    data["tech_stack"] = json.dumps(data.get("tech_stack", []))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, data)
            result = cur.fetchone()
            return result[0] if result else None


def get_unranked_companies(limit: int = 100) -> List[Dict]:
    """Return companies that have not yet been scored."""
    sql = """
        SELECT id, company_name, description, tech_stack, website
        FROM   companies
        WHERE  relevance_score IS NULL
        LIMIT  %(limit)s;
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, {"limit": limit})
            return [dict(r) for r in cur.fetchall()]


def update_company_score(company_id: int, score: float, reasoning: str) -> None:
    """Persist LLM relevance score and promote qualified companies."""
    sql = """
        UPDATE companies
        SET    relevance_score = %(score)s,
               reasoning       = %(reasoning)s,
               is_qualified    = (%(score)s > 7),
               ranked_at       = NOW()
        WHERE  id = %(id)s;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"score": score, "reasoning": reasoning, "id": company_id})
    logger.debug(f"Company {company_id} scored {score}.")


def get_qualified_companies(already_emailed: bool = False) -> List[Dict]:
    """
    Return qualified companies that haven't received an email yet.
    Set already_emailed=True to include ones that have.
    """
    if already_emailed:
        where_clause = "WHERE c.is_qualified = TRUE"
    else:
        where_clause = """
            WHERE c.is_qualified = TRUE
            AND   c.contact_email IS NOT NULL
            AND   c.id NOT IN (SELECT DISTINCT company_id FROM emails_sent WHERE status = 'sent')
        """
    sql = f"""
        SELECT c.id, c.company_name, c.website,
               c.contact_email, c.description, c.tech_stack,
               c.relevance_score, c.reasoning
        FROM   companies c
        {where_clause}
        ORDER BY c.relevance_score DESC;
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def get_daily_sent_count() -> int:
    """Return number of emails successfully sent today."""
    sql = "SELECT sent_today FROM daily_send_count;"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return int(row[0]) if row else 0


def log_email(company_id: int, to_address: str, subject: str,
              body: str, template: str, status: str = "pending",
              error_message: str = None) -> int:
    """Insert an email record and return its id."""
    sql = """
        INSERT INTO emails_sent
            (company_id, to_address, subject, body, template_used, status, error_message)
        VALUES
            (%(company_id)s, %(to_address)s, %(subject)s, %(body)s,
             %(template)s, %(status)s, %(error_message)s)
        RETURNING id;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "company_id": company_id,
                "to_address": to_address,
                "subject": subject,
                "body": body,
                "template": template,
                "status": status,
                "error_message": error_message,
            })
            return cur.fetchone()[0]


def update_email_status(email_id: int, status: str, error_message: str = None) -> None:
    """Update the delivery status of an email record."""
    sql = """
        UPDATE emails_sent
        SET    status = %(status)s, error_message = %(error)s
        WHERE  id = %(id)s;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"status": status, "error": error_message, "id": email_id})


# ---------------------------------------------------------------------------
# Reply helpers
# ---------------------------------------------------------------------------

def log_reply(company_id: Optional[int], from_address: str,
              subject: str, raw_message: str, classification: str) -> int:
    """Insert a received reply and return its id."""
    sql = """
        INSERT INTO replies
            (company_id, from_address, subject, raw_message, classification)
        VALUES
            (%(company_id)s, %(from_address)s, %(subject)s,
             %(raw_message)s, %(classification)s)
        RETURNING id;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "company_id": company_id,
                "from_address": from_address,
                "subject": subject,
                "raw_message": raw_message,
                "classification": classification,
            })
            return cur.fetchone()[0]


def get_company_id_by_email(email_address: str) -> Optional[int]:
    """Resolve an email address back to a company id (if known)."""
    sql = "SELECT id FROM companies WHERE contact_email = %(email)s LIMIT 1;"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"email": email_address})
            row = cur.fetchone()
            return row[0] if row else None


def get_unnotified_replies() -> List[Dict]:
    """Return reply rows that have not yet triggered a Telegram notification."""
    sql = """
        SELECT r.id, r.from_address, r.subject, r.classification,
               c.company_name
        FROM   replies r
        LEFT JOIN companies c ON c.id = r.company_id
        WHERE  r.notified = FALSE;
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


def mark_reply_notified(reply_id: int) -> None:
    """Mark a reply as notified."""
    sql = "UPDATE replies SET notified = TRUE WHERE id = %(id)s;"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"id": reply_id})
