"""
Main Pipeline Orchestrator

Runs the full daily HNWI/UHNWI prospect detection pipeline:
  1. Collect news (Tavily + RSS)
  2. Filter wealth signals
  3. Extract prospects via Claude API
  4. Score & rank
  5. Generate HTML newsletter
  6. Persist to TinyDB
  7. Send to subscribers (Resend)
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env before any other local imports  
load_dotenv()

from backend.collectors.news_collector import NewsCollector
from backend.db.database import ProspectDB, RunLogDB, SubscriberDB
from backend.newsletter.generator import generate_newsletter_html
from backend.newsletter.sender import NewsletterSender
from backend.processors.extractor import ProspectExtractor
from backend.processors.scorer import rank_prospects
from backend.processors.signal_detector import filter_articles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


# ─── Config ───────────────────────────────────────────────────────────────────

MAX_PROSPECTS = int(os.getenv("MAX_PROSPECTS", "5"))
MAX_TAVILY_PER_QUERY = int(os.getenv("MAX_TAVILY_PER_QUERY", "5"))
MAX_RSS_PER_FEED = int(os.getenv("MAX_RSS_PER_FEED", "10"))
MIN_SIGNAL_SCORE = float(os.getenv("MIN_SIGNAL_SCORE", "0.2"))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "60"))
MIN_PROSPECT_SCORE = int(os.getenv("MIN_PROSPECT_SCORE", "40"))


# ─── Pipeline ────────────────────────────────────────────────────────────────

class PipelineResult:
    def __init__(self):
        self.articles_collected: int = 0
        self.articles_signaled: int = 0
        self.prospects_extracted: int = 0
        self.prospects_ranked: int = 0
        self.newsletter_html: str = ""
        self.run_id: str = ""
        self.recipients_count: int = 0
        self.sent_count: int = 0
        self.success: bool = False
        self.error: str | None = None


def run_pipeline(
    send_emails: bool = True,
    dry_run: bool = False,
    test_email: str | None = None,
) -> PipelineResult:
    """
    Execute the full pipeline.

    Args:
        send_emails: Whether to dispatch the newsletter. Default True.
        dry_run: If True, skip email sending and DB writes.
        test_email: If set, send only to this address (used for previews).
    """
    result = PipelineResult()
    run_date = datetime.now(timezone.utc)
    result.run_id = run_date.strftime("%Y-%m-%d")

    logger.info(f"═══ Pipeline starting — run_id={result.run_id} ═══")

    try:
        # ── Step 1: Collect ───────────────────────────────────────────────────
        logger.info("Step 1/5 — Collecting news...")
        # Sources gratuites par défaut ; Tavily activé seulement si clé présente
        use_tavily = bool(os.getenv("TAVILY_API_KEY"))
        collector = NewsCollector(
            use_rss=True,
            use_duckduckgo=True,
            use_tavily=use_tavily,
        )
        articles = collector.collect(
            max_ddg_per_query=int(os.getenv("MAX_DDG_PER_QUERY", "5")),
            max_tavily_per_query=MAX_TAVILY_PER_QUERY,
            max_rss_per_feed=MAX_RSS_PER_FEED,
        )
        result.articles_collected = len(articles)
        logger.info(f"  → {result.articles_collected} articles collected")

        if not articles:
            result.error = "No articles collected"
            logger.warning("No articles — aborting pipeline")
            return result

        # ── Step 2: Signal detection ──────────────────────────────────────────
        logger.info("Step 2/5 — Filtering wealth signals...")
        signaled = filter_articles(articles, min_signal_score=MIN_SIGNAL_SCORE)
        result.articles_signaled = len(signaled)
        logger.info(f"  → {result.articles_signaled} articles with wealth signals")

        if not signaled:
            result.error = "No wealth signals detected"
            logger.warning("No signaled articles — aborting pipeline")
            return result

        # Limit to top 30 most-signaled to control LLM cost
        signaled = signaled[:30]

        # ── Step 3: LLM Extraction ────────────────────────────────────────────
        logger.info("Step 3/5 — Extracting prospects via Claude API...")
        extractor = ProspectExtractor()
        raw_prospects = extractor.extract_batch(signaled, min_confidence=MIN_CONFIDENCE)
        result.prospects_extracted = len(raw_prospects)
        logger.info(f"  → {result.prospects_extracted} qualified prospects extracted")

        if not raw_prospects:
            result.error = "No prospects extracted"
            logger.warning("No prospects — aborting pipeline")
            return result

        # ── Step 4: Score & Rank ──────────────────────────────────────────────
        logger.info("Step 4/5 — Scoring and ranking...")
        top_prospects = rank_prospects(
            raw_prospects,
            top_n=MAX_PROSPECTS,
            min_score=MIN_PROSPECT_SCORE,
        )
        result.prospects_ranked = len(top_prospects)
        logger.info(f"  → Top {result.prospects_ranked} prospects selected")

        for i, sp in enumerate(top_prospects, 1):
            logger.info(
                f"     #{i} {sp.name} ({sp.event_type}) — "
                f"score={sp.potential_score} urgency={sp.urgency_score} "
                f"amount={sp.amount_label}"
            )

        # ── Step 5: Generate newsletter ───────────────────────────────────────
        logger.info("Step 5/5 — Generating newsletter...")
        newsletter_html = generate_newsletter_html(top_prospects, date=run_date)
        result.newsletter_html = newsletter_html

        # Toujours sauvegarder le HTML sur disque (dry-run ou pas)
        html_path = Path(os.getenv("DB_PATH", "data/db.json")).parent / f"newsletter_{result.run_id}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(newsletter_html, encoding="utf-8")
        logger.info(f"  → Newsletter HTML sauvegardée : {html_path}")
        logger.info(f"    Ouvrir dans le navigateur : open {html_path}")

        if dry_run:
            logger.info("DRY RUN — skipping DB write and email send")
            result.success = True
            return result

        # ── Persist ───────────────────────────────────────────────────────────
        ProspectDB.save_run(top_prospects, run_date=run_date)

        # ── Send emails ───────────────────────────────────────────────────────
        resend_key = os.getenv("RESEND_API_KEY", "").strip()
        from_email  = os.getenv("FROM_EMAIL", "").strip()

        if not send_emails:
            logger.info("Envoi email désactivé (--dry-run).")
        elif not resend_key:
            logger.warning(
                "⚠️  RESEND_API_KEY absente du .env — email ignoré.\n"
                "   → Créez un compte sur https://resend.com (gratuit) et copiez la clé."
            )
        elif not from_email:
            logger.warning(
                "⚠️  FROM_EMAIL absent du .env — email ignoré.\n"
                "   → Pour tester sans domaine propre : FROM_EMAIL=onboarding@resend.dev"
            )
        else:
            sender = NewsletterSender()

            if test_email:
                logger.info(f"Envoi email de test à {test_email}…")
                ok = sender.send_test(test_email, newsletter_html)
                result.recipients_count = 1
                result.sent_count = 1 if ok else 0
                if not ok:
                    logger.warning(
                        "⚠️  Échec de l'envoi. Causes fréquentes :\n"
                        "   1. Domaine FROM_EMAIL non vérifié sur resend.com\n"
                        "   2. RESEND_API_KEY invalide ou révoquée\n"
                        "   → Solution rapide : FROM_EMAIL=onboarding@resend.dev"
                    )
            else:
                recipients = SubscriberDB.get_active()
                result.recipients_count = len(recipients)
                if recipients:
                    logger.info(f"Envoi à {result.recipients_count} abonné(s)…")
                    send_result = sender.send_to_many(recipients, newsletter_html, date=run_date)
                    result.sent_count = send_result.sent_count
                else:
                    logger.info("Aucun abonné actif — envoi ignoré.")

            RunLogDB.log(
                run_id=result.run_id,
                prospect_count=result.prospects_ranked,
                recipient_count=result.recipients_count,
                sent_count=result.sent_count,
                failed_count=result.recipients_count - result.sent_count,
                status="success",
            )

        result.success = True
        logger.info(f"═══ Pipeline completed successfully ═══")

    except Exception as e:
        result.error = str(e)
        result.success = False
        logger.error(f"Pipeline failed: {e}", exc_info=True)

        try:
            RunLogDB.log(
                run_id=result.run_id,
                prospect_count=0,
                recipient_count=0,
                sent_count=0,
                failed_count=0,
                status="error",
                error=str(e),
            )
        except Exception:
            pass

    return result


# ─── Scheduler ───────────────────────────────────────────────────────────────

def start_scheduler():
    """Run the pipeline daily at the configured hour (UTC)."""
    import schedule
    import time

    hour = int(os.getenv("NEWSLETTER_HOUR", "7"))
    logger.info(f"Scheduler started — pipeline will run daily at {hour:02d}:00 UTC")

    schedule.every().day.at(f"{hour:02d}:00").do(run_pipeline)

    while True:
        schedule.run_pending()
        time.sleep(60)


# ─── CLI entrypoint ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HNWI Prospect Pipeline")
    parser.add_argument("--run", action="store_true", help="Run the pipeline immediately")
    parser.add_argument("--schedule", action="store_true", help="Start the daily scheduler")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending emails")
    parser.add_argument("--test-email", type=str, help="Send test newsletter to this email")
    args = parser.parse_args()

    if args.schedule:
        start_scheduler()
    elif args.run or args.test_email or args.dry_run:
        result = run_pipeline(
            send_emails=not args.dry_run,
            dry_run=args.dry_run,
            test_email=args.test_email,
        )
        if result.success:
            print(f"\n✅ Pipeline OK — {result.prospects_ranked} prospects, "
                  f"{result.sent_count} emails sent")
            sys.exit(0)
        else:
            print(f"\n❌ Pipeline FAILED: {result.error}")
            sys.exit(1)
    else:
        parser.print_help()
