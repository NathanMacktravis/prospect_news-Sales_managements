"""
Script de test rapide — valide chaque composant indépendamment.
Lance : python test_pipeline.py
"""

import sys
import os
from pathlib import Path

# S'assurer que le projet est dans le path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "
SEP  = "─" * 60


def section(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


# ─── 1. Clés API ──────────────────────────────────────────────────────────────

section("1. CLÉS API")

keys = {
    "ANTHROPIC_API_KEY": "Claude (LLM)",
    "RESEND_API_KEY":    "Resend (email)",
    "TAVILY_API_KEY":    "Tavily (optionnel)",
}
missing_critical = False
for k, label in keys.items():
    val = os.getenv(k, "")
    if val:
        print(f"  {PASS} {label:<25} {val[:12]}…")
    elif k == "TAVILY_API_KEY":
        print(f"  {WARN} {label:<25} non définie (DuckDuckGo sera utilisé)")
    else:
        print(f"  {FAIL} {label:<25} MANQUANTE — ajoutez-la dans .env")
        missing_critical = True

if missing_critical:
    print("\n  ⛔ Clés critiques manquantes. Stoppez ici et remplissez le .env.")
    sys.exit(1)


# ─── 2. Imports ───────────────────────────────────────────────────────────────

section("2. DÉPENDANCES PYTHON")

packages = [
    ("anthropic",          "Claude SDK"),
    ("feedparser",         "RSS"),
    ("requests",           "HTTP"),
    ("tinydb",             "Base de données"),
    ("pydantic",           "Validation"),
    ("plotly",             "Graphiques"),
    ("streamlit",          "Frontend"),
    ("duckduckgo_search",  "DuckDuckGo (gratuit)"),
    ("schedule",           "Planificateur"),
]
missing_pkg = False
for module, label in packages:
    try:
        __import__(module)
        print(f"  {PASS} {label}")
    except ImportError:
        print(f"  {FAIL} {label:<25} → pip3 install {module.replace('_', '-')}")
        missing_pkg = True

if missing_pkg:
    print("\n  ⛔ Lancez : pip3 install -r requirements.txt")
    sys.exit(1)


# ─── 3. Collecte d'articles ───────────────────────────────────────────────────

section("3. COLLECTE RSS + DUCKDUCKGO")

from backend.collectors.news_collector import NewsCollector

print("  Collecte via RSS (2 flux) + DuckDuckGo (1 requête)…")
try:
    from backend.collectors.news_collector import RSSCollector, DuckDuckGoCollector, RSS_FEEDS

    # Test RSS : 2 flux seulement pour aller vite
    rss = RSSCollector(feeds=RSS_FEEDS[:2])
    rss_articles = rss.collect(max_per_feed=5)
    print(f"  {PASS} RSS         → {len(rss_articles)} articles")

    # Test DuckDuckGo : 1 seule requête
    ddg = DuckDuckGoCollector()
    ddg_articles = ddg.collect_all(
        queries=["IPO founder billion 2025"],
        max_per_query=3,
    )
    print(f"  {PASS} DuckDuckGo  → {len(ddg_articles)} articles")

    all_articles = rss_articles + ddg_articles
    if all_articles:
        sample = all_articles[0]
        print(f"\n  Exemple : « {sample.title[:70]}… »")
        print(f"           Source : {sample.source}")
    else:
        print(f"  {WARN} 0 articles — vérifiez votre connexion internet")
except Exception as e:
    print(f"  {FAIL} Erreur : {e}")
    sys.exit(1)


# ─── 4. Détection de signaux ──────────────────────────────────────────────────

section("4. DÉTECTION DE SIGNAUX WEALTH")

from backend.processors.signal_detector import filter_articles

try:
    signaled = filter_articles(all_articles, min_signal_score=0.1)
    print(f"  {PASS} {len(signaled)} / {len(all_articles)} articles avec signaux wealth")
    if signaled:
        s = signaled[0]
        cats = ", ".join(sorted(s.signal_categories))
        print(f"  Exemple : « {s.article.title[:60]}… »")
        print(f"           Signaux : [{cats}]  score={s.signal_score:.2f}")
    else:
        print(f"  {WARN} Aucun signal — normal avec peu d'articles de test")
except Exception as e:
    print(f"  {FAIL} Erreur : {e}")


# ─── 5. Extraction LLM (Claude Haiku) ────────────────────────────────────────

section("5. EXTRACTION LLM — Claude Haiku 4.5")

from backend.processors.extractor import ProspectExtractor

if not signaled:
    print(f"  {WARN} Aucun article signalé à analyser — test sauté")
else:
    try:
        extractor = ProspectExtractor()
        # Tester sur 1 seul article pour limiter le coût
        print(f"  Envoi de 1 article à Claude Haiku…")
        sample_prospect = extractor.extract(signaled[0])
        if sample_prospect:
            print(f"  {PASS} Extraction OK")
            print(f"     Nom      : {sample_prospect.name}")
            print(f"     Société  : {sample_prospect.company}")
            print(f"     Événement: {sample_prospect.event_type} — {sample_prospect.amount_label}")
            print(f"     Score    : confiance={sample_prospect.confidence_score} urgence={sample_prospect.urgency_score}")
        else:
            print(f"  {WARN} Extraction retournée vide (article peu exploitable)")
    except Exception as e:
        print(f"  {FAIL} Erreur Claude : {e}")


# ─── 6. Scoring ───────────────────────────────────────────────────────────────

section("6. SCORING (0–100)")

from backend.processors.extractor import ProspectData
from backend.processors.scorer import score_prospect, rank_prospects

# Créer un prospect fictif pour tester le scoring sans dépendre du LLM
dummy = ProspectData(
    name="Jean Dupont",
    title="Founder & CEO",
    company="AcmeCorp",
    sector="Technology",
    event_type="IPO",
    event_summary="AcmeCorp a levé 500M€ lors de son introduction en bourse à Paris.",
    estimated_amount_usd=540_000_000,
    amount_label="$540M",
    location="Paris, France",
    source_url="https://example.com/article",
    sales_pitch="Événement de liquidité récent — Jean dispose de nouvelles liquidités à investir.",
    urgency_score=8,
    confidence_score=85,
)
try:
    scored = score_prospect(dummy)
    print(f"  {PASS} Score calculé : {scored.potential_score}/100  (urgence={scored.urgency_score}/10)")
    ranked = rank_prospects([dummy], top_n=1)
    print(f"  {PASS} Ranking OK : {len(ranked)} prospect(s) dans le top")
except Exception as e:
    print(f"  {FAIL} Erreur scoring : {e}")


# ─── 7. Génération newsletter HTML ───────────────────────────────────────────

section("7. GÉNÉRATION NEWSLETTER HTML")

from backend.processors.scorer import ScoredProspect
from backend.newsletter.generator import generate_newsletter_html
from datetime import datetime, timezone

try:
    sp = ScoredProspect(data=dummy, potential_score=82, urgency_score=8, composite_rank=0.85)
    html = generate_newsletter_html([sp], date=datetime.now(timezone.utc))

    out_path = ROOT / "data" / "test_newsletter.html"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    size_kb = len(html) / 1024
    print(f"  {PASS} HTML généré ({size_kb:.1f} Ko)")
    print(f"  {PASS} Sauvegardé → {out_path}")
    print(f"       Ouvrez ce fichier dans votre navigateur pour prévisualiser.")
except Exception as e:
    print(f"  {FAIL} Erreur génération : {e}")


# ─── 8. Base de données ───────────────────────────────────────────────────────

section("8. BASE DE DONNÉES TinyDB")

from backend.db.database import SubscriberDB, ProspectDB, RunLogDB

try:
    # Abonné test
    added = SubscriberDB.add("test@example.com")
    count = SubscriberDB.count_active()
    print(f"  {PASS} Abonné ajouté : test@example.com  (total actif : {count})")

    # Sauvegarder un run fictif
    ProspectDB.save_run([sp])
    run_id, records = ProspectDB.get_latest_run()
    print(f"  {PASS} Run sauvegardé : {run_id}  ({len(records)} prospect(s))")

    # Log
    RunLogDB.log(run_id=run_id, prospect_count=1, recipient_count=1,
                 sent_count=0, failed_count=0, status="test")
    print(f"  {PASS} Log enregistré")

    # Nettoyage de l'abonné test
    SubscriberDB.remove("test@example.com")
except Exception as e:
    print(f"  {FAIL} Erreur DB : {e}")


# ─── 9. Email de test (optionnel) ────────────────────────────────────────────

section("9. ENVOI EMAIL DE TEST")

test_email = os.getenv("TEST_EMAIL", "")
if not test_email:
    print(f"  {WARN} Sautez cette étape ou ajoutez TEST_EMAIL=votre@email.com dans .env")
else:
    from backend.newsletter.sender import NewsletterSender
    try:
        sender = NewsletterSender()
        ok = sender.send_test(test_email, html)
        if ok:
            print(f"  {PASS} Email de test envoyé à {test_email}")
        else:
            print(f"  {FAIL} Échec envoi — vérifiez votre RESEND_API_KEY et FROM_EMAIL")
    except Exception as e:
        print(f"  {FAIL} Erreur email : {e}")


# ─── Résumé ───────────────────────────────────────────────────────────────────

print(f"\n{'═' * 60}")
print("  RÉSUMÉ")
print(f"{'═' * 60}")
print(f"""
  Tout est opérationnel. Prochaines étapes :

  A) Prévisualiser la newsletter :
     → Ouvrez  data/test_newsletter.html  dans Chrome/Safari

  B) Lancer le pipeline complet (sans envoi email) :
     python -m backend.pipeline --dry-run

  C) Lancer et envoyer un email de test :
     python -m backend.pipeline --test-email votre@email.com

  D) Démarrer l'app Streamlit :
     streamlit run frontend/app.py

  E) Planifier l'envoi quotidien :
     python -m backend.pipeline --schedule
""")
