"""
Database layer:
  - SubscriberDB  → Supabase  (cloud PostgreSQL — accessible from any machine)
  - ProspectDB    → TinyDB    (local JSON — ephemeral, machine-local)
  - RunLogDB      → TinyDB    (local JSON — ephemeral, machine-local)

Supabase table required (run once in the Supabase SQL editor):

    CREATE TABLE subscribers (
        id         BIGSERIAL PRIMARY KEY,
        email      TEXT        UNIQUE NOT NULL,
        active     BOOLEAN     NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from tinydb import TinyDB, Query
from tinydb.middlewares import CachingMiddleware
from tinydb.storages import JSONStorage
from supabase import create_client, Client

from backend.processors.extractor import ProspectData
from backend.processors.scorer import ScoredProspect

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/db.json")


# ─── Supabase client (lazy singleton) ────────────────────────────────────────

_supabase_client: Client | None = None


def _get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_KEY", "").strip()
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set. "
                "Create a free project at https://supabase.com and copy the "
                "Project URL + anon/public key."
            )
        _supabase_client = create_client(url, key)
    return _supabase_client


# ─── TinyDB helper (prospects + run logs only) ───────────────────────────────

def _get_db() -> TinyDB:
    """Return a TinyDB instance with caching middleware."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    return TinyDB(DB_PATH, storage=CachingMiddleware(JSONStorage))


# ─── Subscriber operations (Supabase) ────────────────────────────────────────

class SubscriberDB:
    TABLE = "subscribers"

    @staticmethod
    def add(email: str) -> bool:
        """Add a subscriber. Returns False if already exists."""
        email = email.strip().lower()
        sb = _get_supabase()
        existing = sb.table(SubscriberDB.TABLE).select("email").eq("email", email).execute()
        if existing.data:
            logger.info(f"Subscriber already exists: {email}")
            return False
        sb.table(SubscriberDB.TABLE).insert({
            "email": email,
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        logger.info(f"New subscriber: {email}")
        return True

    @staticmethod
    def remove(email: str) -> bool:
        """Deactivate a subscriber (soft delete). Returns True if found."""
        email = email.strip().lower()
        sb = _get_supabase()
        existing = sb.table(SubscriberDB.TABLE).select("email").eq("email", email).execute()
        if not existing.data:
            return False
        sb.table(SubscriberDB.TABLE).update({"active": False}).eq("email", email).execute()
        logger.info(f"Unsubscribed: {email}")
        return True

    @staticmethod
    def get_active() -> list[str]:
        """Return list of active subscriber emails."""
        sb = _get_supabase()
        res = sb.table(SubscriberDB.TABLE).select("email").eq("active", True).execute()
        return [r["email"] for r in res.data]

    @staticmethod
    def get_all() -> list[dict]:
        """Return all subscriber records."""
        sb = _get_supabase()
        res = sb.table(SubscriberDB.TABLE).select("*").order("created_at", desc=True).execute()
        return res.data

    @staticmethod
    def set_active(email: str, active: bool = True) -> bool:
        """Update the active status of an existing subscriber. Returns True if found."""
        email = email.strip().lower()
        sb = _get_supabase()
        existing = sb.table(SubscriberDB.TABLE).select("email").eq("email", email).execute()
        if not existing.data:
            return False
        sb.table(SubscriberDB.TABLE).update({"active": active}).eq("email", email).execute()
        logger.info(f"Subscriber {email} active={active}")
        return True

    @staticmethod
    def count_active() -> int:
        return len(SubscriberDB.get_active())


# ─── Prospect storage ─────────────────────────────────────────────────────────

class ProspectDB:
    TABLE = "prospects"

    @staticmethod
    def save_run(
        prospects: list[ScoredProspect],
        run_date: Optional[datetime] = None,
    ) -> str:
        """Persist a list of scored prospects for today's run."""
        if run_date is None:
            run_date = datetime.now(timezone.utc)

        run_id = run_date.strftime("%Y-%m-%d")

        with _get_db() as db:
            table = db.table(ProspectDB.TABLE)
            Q = Query()
            # Remove any existing run for the same date
            table.remove(Q.run_id == run_id)

            records = []
            for rank, sp in enumerate(prospects, start=1):
                d = sp.data
                records.append({
                    "run_id": run_id,
                    "rank": rank,
                    "name": d.name,
                    "title": d.title,
                    "company": d.company,
                    "sector": d.sector,
                    "event_type": d.event_type,
                    "event_summary": d.event_summary,
                    "estimated_amount_usd": d.estimated_amount_usd,
                    "amount_label": d.amount_label,
                    "location": d.location,
                    "source_url": d.source_url,
                    "published_at": d.published_at,
                    "sales_pitch": d.sales_pitch,
                    "urgency_score": d.urgency_score,
                    "confidence_score": d.confidence_score,
                    "potential_score": sp.potential_score,
                    "extracted_at": d.extracted_at,
                })

            table.insert_multiple(records)
            logger.info(f"Saved {len(records)} prospects for run {run_id}")
            return run_id

    @staticmethod
    def get_latest_run() -> tuple[str | None, list[dict]]:
        """Return the most recent run_id and its prospect records."""
        with _get_db() as db:
            table = db.table(ProspectDB.TABLE)
            all_records = table.all()
            if not all_records:
                return None, []

            # Find most recent run_id (YYYY-MM-DD string sorts correctly)
            latest_id = max(r["run_id"] for r in all_records)
            run_records = [r for r in all_records if r["run_id"] == latest_id]
            run_records.sort(key=lambda r: r["rank"])
            return latest_id, run_records

    @staticmethod
    def get_run(run_id: str) -> list[dict]:
        """Get prospects for a specific run date (YYYY-MM-DD)."""
        with _get_db() as db:
            Q = Query()
            records = db.table(ProspectDB.TABLE).search(Q.run_id == run_id)
            return sorted(records, key=lambda r: r["rank"])

    @staticmethod
    def list_run_ids() -> list[str]:
        """Return all run IDs sorted descending (most recent first)."""
        with _get_db() as db:
            all_records = db.table(ProspectDB.TABLE).all()
            ids = sorted({r["run_id"] for r in all_records}, reverse=True)
            return ids


# ─── Newsletter run log ───────────────────────────────────────────────────────

class RunLogDB:
    TABLE = "run_log"

    @staticmethod
    def log(
        run_id: str,
        prospect_count: int,
        recipient_count: int,
        sent_count: int,
        failed_count: int,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        with _get_db() as db:
            db.table(RunLogDB.TABLE).insert({
                "run_id": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "prospect_count": prospect_count,
                "recipient_count": recipient_count,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "status": status,
                "error": error,
            })

    @staticmethod
    def get_recent(limit: int = 10) -> list[dict]:
        with _get_db() as db:
            records = db.table(RunLogDB.TABLE).all()
            records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
            return records[:limit]
