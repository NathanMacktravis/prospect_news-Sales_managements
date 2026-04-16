"""
Database layer — 100 % Supabase (cloud PostgreSQL):
  - SubscriberDB  → table `subscribers`
  - ProspectDB    → table `prospects`
  - RunLogDB      → table `run_log`

SQL à exécuter une fois dans le SQL Editor de Supabase
(Settings → SQL Editor) :

    CREATE TABLE subscribers (
        id         BIGSERIAL PRIMARY KEY,
        email      TEXT        UNIQUE NOT NULL,
        active     BOOLEAN     NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE prospects (
        id                   BIGSERIAL PRIMARY KEY,
        run_id               TEXT    NOT NULL,
        rank                 INTEGER NOT NULL,
        name                 TEXT,
        title                TEXT,
        company              TEXT,
        sector               TEXT,
        event_type           TEXT,
        event_summary        TEXT,
        estimated_amount_usd NUMERIC,
        amount_label         TEXT,
        location             TEXT,
        source_url           TEXT,
        published_at         TEXT,
        sales_pitch          TEXT,
        urgency_score        INTEGER,
        confidence_score     INTEGER,
        potential_score      NUMERIC,
        extracted_at         TEXT,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE run_log (
        id               BIGSERIAL PRIMARY KEY,
        run_id           TEXT NOT NULL,
        timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        prospect_count   INTEGER,
        recipient_count  INTEGER,
        sent_count       INTEGER,
        failed_count     INTEGER,
        status           TEXT,
        error            TEXT
    );
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

from backend.processors.extractor import ProspectData
from backend.processors.scorer import ScoredProspect

logger = logging.getLogger(__name__)


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


# ─── Subscriber operations ────────────────────────────────────────────────────

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
        sb = _get_supabase()

        # Remove any existing run for the same date
        sb.table(ProspectDB.TABLE).delete().eq("run_id", run_id).execute()

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

        sb.table(ProspectDB.TABLE).insert(records).execute()
        logger.info(f"Saved {len(records)} prospects for run {run_id}")
        return run_id

    @staticmethod
    def get_latest_run() -> tuple[str | None, list[dict]]:
        """Return the most recent run_id and its prospect records."""
        sb = _get_supabase()
        # Get the most recent run_id
        id_res = (
            sb.table(ProspectDB.TABLE)
            .select("run_id")
            .order("run_id", desc=True)
            .limit(1)
            .execute()
        )
        if not id_res.data:
            return None, []
        latest_id = id_res.data[0]["run_id"]
        # Get all prospects for that run, ordered by rank
        res = (
            sb.table(ProspectDB.TABLE)
            .select("*")
            .eq("run_id", latest_id)
            .order("rank")
            .execute()
        )
        return latest_id, res.data

    @staticmethod
    def get_run(run_id: str) -> list[dict]:
        """Get prospects for a specific run date (YYYY-MM-DD)."""
        sb = _get_supabase()
        res = (
            sb.table(ProspectDB.TABLE)
            .select("*")
            .eq("run_id", run_id)
            .order("rank")
            .execute()
        )
        return res.data

    @staticmethod
    def list_run_ids() -> list[str]:
        """Return all run IDs sorted descending (most recent first)."""
        sb = _get_supabase()
        res = sb.table(ProspectDB.TABLE).select("run_id").execute()
        ids = sorted({r["run_id"] for r in res.data}, reverse=True)
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
        sb = _get_supabase()
        sb.table(RunLogDB.TABLE).insert({
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prospect_count": prospect_count,
            "recipient_count": recipient_count,
            "sent_count": sent_count,
            "failed_count": failed_count,
            "status": status,
            "error": error,
        }).execute()

    @staticmethod
    def get_recent(limit: int = 10) -> list[dict]:
        sb = _get_supabase()
        res = (
            sb.table(RunLogDB.TABLE)
            .select("*")
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data
