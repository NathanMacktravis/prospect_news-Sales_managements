"""
Streamlit Frontend — HNWI Prospect Intelligence
  - Email subscription form
  - Newsletter preview (latest run)
  - Dashboard: prospect table + Plotly chart
  - Admin: trigger pipeline, view run logs
"""

from __future__ import annotations

import os
import sys
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Add project root to path so we can import backend modules
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="HNWI Prospect Intelligence",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Primary colour overrides */
  :root { --primary: #1A3C5E; --accent: #C9A84C; }
  [data-testid="stSidebar"] { background: #1A3C5E !important; }
  [data-testid="stSidebar"] * { color: white !important; }
  [data-testid="stSidebar"] a { color: #C9A84C !important; }
  .metric-card {
    background: white;
    border-radius: 8px;
    padding: 20px;
    border: 1px solid #DEE2E6;
    box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    text-align: center;
  }
  .metric-card h2 { color: #1A3C5E; margin: 0 0 4px; font-size: 2rem; }
  .metric-card p  { color: #6C757D; margin: 0; font-size: 13px; }
  .prospect-card  {
    background: white; border-radius: 8px;
    padding: 16px 20px; margin-bottom: 12px;
    border: 1px solid #DEE2E6;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
  }
  .badge {
    display: inline-block; padding: 2px 10px;
    border-radius: 12px; font-size: 11px; font-weight: 700;
  }
  .score-pill {
    display: inline-block; background: #1A3C5E; color: white;
    border-radius: 20px; padding: 2px 12px; font-size: 13px;
    font-weight: 700;
  }
</style>
""", unsafe_allow_html=True)

# ── Lazy imports (only when DB exists) ───────────────────────────────────────

def _try_import_db():
    try:
        from backend.db.database import SubscriberDB, ProspectDB, RunLogDB
        return SubscriberDB, ProspectDB, RunLogDB
    except Exception as e:
        return None, None, None


def _email_valid(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 💎 HNWI Intelligence")
    st.markdown("---")
    page = st.radio(
        "Navigation",
        ["🏠 Accueil & Inscription", "📊 Dashboard", "📧 Aperçu Newsletter", "⚙️ Admin"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    SubscriberDB, ProspectDB, RunLogDB = _try_import_db()
    if SubscriberDB:
        count = SubscriberDB.count_active()
        st.markdown(f"**{count}** abonné(s) actif(s)")
        run_ids = ProspectDB.list_run_ids() if ProspectDB else []
        if run_ids:
            st.markdown(f"Dernière analyse: **{run_ids[0]}**")
    st.markdown("---")
    st.markdown(
        "<small style='color:rgba(255,255,255,0.5)'>Powered by Claude AI · Resend · TinyDB</small>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: ACCUEIL & INSCRIPTION
# ─────────────────────────────────────────────────────────────────────────────

if "🏠 Accueil & Inscription" in page:
    # Hero section
    st.markdown("""
    <div style="background:linear-gradient(135deg,#1A3C5E,#2D5F8A);
                border-radius:12px;padding:40px;margin-bottom:24px;text-align:center;">
      <div style="font-size:48px;margin-bottom:12px;">💎</div>
      <h1 style="color:white;margin:0 0 8px;font-size:32px;">HNWI Prospect Intelligence</h1>
      <p style="color:rgba(255,255,255,0.8);font-size:16px;margin:0 0 20px;">
        Détectez chaque jour les 5 meilleurs prospects HNWI/UHNWI via l'IA —
        IPO, M&A, levées de fonds, nominations.
      </p>
      <p style="color:#C9A84C;font-size:14px;font-weight:600;margin:0;">
        Newsletter quotidienne · Sales-ready · Liens sources inclus
      </p>
    </div>
    """, unsafe_allow_html=True)

    # Value props
    col1, col2, col3, col4 = st.columns(4)
    for col, icon, label, desc in [
        (col1, "🔍", "Collecte Auto", "Tavily + RSS financiers"),
        (col2, "🧠", "IA Claude", "Extraction & scoring LLM"),
        (col3, "📈", "Score 0–100", "Potentiel + Urgence"),
        (col4, "📧", "Newsletter", "Envoi quotidien 7h UTC"),
    ]:
        with col:
            st.markdown(f"""
            <div class="metric-card">
              <div style="font-size:28px;margin-bottom:8px;">{icon}</div>
              <strong style="color:#1A3C5E;">{label}</strong>
              <p>{desc}</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Subscription form ─────────────────────────────────────────────────────
    st.markdown("### ✉️ Recevoir la newsletter quotidienne")
    st.markdown("Entrez votre adresse email pour recevoir chaque matin les 5 meilleurs prospects HNWI.")

    with st.form("subscribe_form", clear_on_submit=True):
        col_email, col_btn = st.columns([3, 1])
        with col_email:
            email_input = st.text_input(
                "Email",
                placeholder="vous@exemple.com",
                label_visibility="collapsed",
            )
        with col_btn:
            submitted = st.form_submit_button("S'inscrire 🚀", use_container_width=True)

        if submitted:
            email_clean = email_input.strip().lower()
            if not email_clean:
                st.error("Veuillez entrer votre email.")
            elif not _email_valid(email_clean):
                st.error("Email invalide. Veuillez vérifier le format.")
            elif SubscriberDB is None:
                st.warning("Base de données non disponible. Vérifiez la configuration.")
            else:
                added = SubscriberDB.add(email_clean)
                if added:
                    st.success(f"🎉 {email_clean} inscrit avec succès ! Vous recevrez la prochaine newsletter.")
                else:
                    st.info(f"📌 {email_clean} est déjà inscrit.")

    # ── Unsubscribe section ───────────────────────────────────────────────────
    with st.expander("Se désabonner"):
        with st.form("unsubscribe_form", clear_on_submit=True):
            unsub_email = st.text_input("Email à désabonner", label_visibility="collapsed",
                                         placeholder="votre@email.com")
            unsub_btn = st.form_submit_button("Se désabonner")
            if unsub_btn and unsub_email:
                if SubscriberDB:
                    removed = SubscriberDB.remove(unsub_email.strip().lower())
                    if removed:
                        st.success("Vous avez été désabonné.")
                    else:
                        st.warning("Email non trouvé.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

elif "📊 Dashboard" in page:
    st.markdown("## 📊 Dashboard Prospects")

    if ProspectDB is None:
        st.warning("Base de données non disponible.")
        st.stop()

    run_ids = ProspectDB.list_run_ids()
    if not run_ids:
        st.info("Aucune analyse effectuée pour le moment. Lancez le pipeline via l'onglet Admin.")
        st.stop()

    # Run selector
    selected_run = st.selectbox("Sélectionner une analyse", run_ids, index=0)
    records = ProspectDB.get_run(selected_run)

    if not records:
        st.info("Aucun prospect pour cette date.")
        st.stop()

    # ── KPI row ───────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    top = records[0] if records else {}
    avg_score = round(sum(r["potential_score"] for r in records) / len(records)) if records else 0
    total_amount = sum(r.get("estimated_amount_usd") or 0 for r in records)

    with c1:
        st.metric("Prospects détectés", len(records))
    with c2:
        st.metric("Score moyen", f"{avg_score}/100")
    with c3:
        st.metric("Top prospect", top.get("name", "—"))
    with c4:
        amount_label = f"${total_amount/1e9:.1f}B" if total_amount >= 1e9 else \
                       f"${total_amount/1e6:.0f}M" if total_amount >= 1e6 else "N/A"
        st.metric("Volume total estimé", amount_label)

    st.markdown("---")

    # ── Plotly chart ──────────────────────────────────────────────────────────
    try:
        import plotly.graph_objects as go

        names = [r["name"].split()[0] + " " + (r["name"].split()[-1] if len(r["name"].split()) > 1 else "")
                 for r in records]
        names = [n[:18] + "…" if len(n) > 18 else n for n in names]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Potentiel (0-100)",
            x=names,
            y=[r["potential_score"] for r in records],
            marker_color="#1A3C5E",
            text=[r["potential_score"] for r in records],
            textposition="outside",
        ))
        fig.add_trace(go.Bar(
            name="Urgence (×10)",
            x=names,
            y=[r["urgency_score"] * 10 for r in records],
            marker_color="#C9A84C",
            text=[r["urgency_score"] * 10 for r in records],
            textposition="outside",
        ))
        fig.update_layout(
            barmode="group",
            title="Potentiel vs Urgence — Top Prospects",
            plot_bgcolor="white",
            paper_bgcolor="white",
            height=350,
            legend=dict(orientation="h", y=1.1),
            yaxis=dict(range=[0, 120]),
        )
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.info("Installez plotly pour voir le graphique : `pip install plotly`")

    st.markdown("---")

    # ── Prospect cards ────────────────────────────────────────────────────────
    BADGE_COLORS = {
        "IPO": "🔵", "M&A": "🟣", "Fundraising": "🟢",
        "Exit": "🟡", "Appointment": "🟠", "Other": "⚫",
    }

    for r in records:
        icon = BADGE_COLORS.get(r["event_type"], "⚫")
        with st.container():
            col_rank, col_main, col_score = st.columns([1, 6, 2])
            with col_rank:
                st.markdown(
                    f"<div style='text-align:center;font-size:32px;font-weight:800;"
                    f"color:#1A3C5E;'>{r['rank']}</div>",
                    unsafe_allow_html=True,
                )
            with col_main:
                st.markdown(
                    f"**{r['name']}** {icon} `{r['event_type']}` · {r['company']}"
                )
                st.markdown(
                    f"<small style='color:#6C757D'>{r['title']} · {r['location']} · "
                    f"<strong style='color:#C9A84C'>{r['amount_label']}</strong></small>",
                    unsafe_allow_html=True,
                )
                st.markdown(r["event_summary"])
                st.markdown(
                    f"<div style='background:#F0F4F8;border-left:3px solid #C9A84C;"
                    f"padding:8px 12px;border-radius:0 4px 4px 0;font-size:13px;"
                    f"color:#1A3C5E;'>"
                    f"💡 <em>{r['sales_pitch']}</em></div>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"[🔗 Source]({r['source_url']})")
            with col_score:
                st.metric("Score", f"{r['potential_score']}/100")
                st.metric("Urgence", f"{r['urgency_score']}/10")
        st.markdown("---")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: APERÇU NEWSLETTER
# ─────────────────────────────────────────────────────────────────────────────

elif "📧 Aperçu Newsletter" in page:
    st.markdown("## 📧 Aperçu de la Dernière Newsletter")

    if ProspectDB is None:
        st.warning("Base de données non disponible.")
        st.stop()

    run_id, records = ProspectDB.get_latest_run()

    if not records:
        st.info("Aucune newsletter générée. Lancez le pipeline dans l'onglet Admin.")
        st.stop()

    st.success(f"Dernière analyse : **{run_id}** · {len(records)} prospects")

    # Regenerate the HTML for preview
    try:
        from backend.processors.extractor import ProspectData
        from backend.processors.scorer import ScoredProspect, score_prospect
        from backend.newsletter.generator import generate_newsletter_html

        prospects_data = []
        for r in records:
            pd = ProspectData(
                name=r["name"],
                title=r["title"],
                company=r["company"],
                sector=r["sector"],
                event_type=r["event_type"],
                event_summary=r["event_summary"],
                estimated_amount_usd=r.get("estimated_amount_usd"),
                amount_label=r["amount_label"],
                location=r["location"],
                source_url=r["source_url"],
                published_at=r.get("published_at"),
                sales_pitch=r["sales_pitch"],
                urgency_score=r["urgency_score"],
                confidence_score=r["confidence_score"],
            )
            sp = ScoredProspect(
                data=pd,
                potential_score=r["potential_score"],
                urgency_score=r["urgency_score"],
                composite_rank=float(r["potential_score"]),
            )
            prospects_data.append(sp)

        run_date = datetime.strptime(run_id, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        html = generate_newsletter_html(prospects_data, date=run_date)

        st.download_button(
            "📥 Télécharger la newsletter HTML",
            data=html,
            file_name=f"newsletter_{run_id}.html",
            mime="text/html",
        )
        st.components.v1.html(html, height=900, scrolling=True)

    except Exception as e:
        st.error(f"Erreur lors de la génération de l'aperçu: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: ADMIN
# ─────────────────────────────────────────────────────────────────────────────

elif "⚙️ Admin" in page:
    st.markdown("## ⚙️ Administration")

    # ── API Keys status ───────────────────────────────────────────────────────
    st.markdown("### 🔑 Configuration des APIs")
    cols = st.columns(3)
    keys = [
        ("ANTHROPIC_API_KEY", "Claude API"),
        ("TAVILY_API_KEY", "Tavily Search"),
        ("RESEND_API_KEY", "Resend Email"),
    ]
    for col, (key_name, label) in zip(cols, keys):
        with col:
            val = os.getenv(key_name, "")
            status = "✅ Configuré" if val else "❌ Manquant"
            color = "#28A745" if val else "#DC3545"
            st.markdown(
                f"<div style='padding:12px;background:white;border-radius:6px;"
                f"border:1px solid #DEE2E6;'>"
                f"<strong>{label}</strong><br>"
                f"<span style='color:{color};font-size:13px;'>{status}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── Run pipeline ──────────────────────────────────────────────────────────
    st.markdown("### 🚀 Lancer le Pipeline")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**Dry Run** (sans envoi d'emails)")
        if st.button("▶️ Lancer le pipeline (dry run)", use_container_width=True):
            with st.spinner("Pipeline en cours..."):
                try:
                    from backend.pipeline import run_pipeline
                    result = run_pipeline(dry_run=True)
                    if result.success:
                        st.success(
                            f"✅ Succès! {result.articles_collected} articles collectés, "
                            f"{result.articles_signaled} signalés, "
                            f"{result.prospects_ranked} prospects."
                        )
                    else:
                        st.error(f"❌ Échec: {result.error}")
                except Exception as e:
                    st.error(f"Erreur: {e}")

    with col_b:
        st.markdown("**Test Email** (envoyer à une seule adresse)")
        test_email = st.text_input("Email de test", placeholder="test@example.com")
        if st.button("📧 Envoyer email de test", use_container_width=True) and test_email:
            if not _email_valid(test_email):
                st.error("Email invalide")
            else:
                with st.spinner("Envoi en cours..."):
                    try:
                        from backend.pipeline import run_pipeline
                        result = run_pipeline(test_email=test_email.strip())
                        if result.success:
                            st.success(f"✅ Email de test envoyé à {test_email}")
                        else:
                            st.error(f"❌ Échec: {result.error}")
                    except Exception as e:
                        st.error(f"Erreur: {e}")

    st.markdown("---")

    # ── Subscribers management ────────────────────────────────────────────────
    st.markdown("### 👥 Abonnés")
    if SubscriberDB:
        all_subs = SubscriberDB.get_all()
        if all_subs:
            import pandas as pd
            df = pd.DataFrame(all_subs)[["email", "active", "created_at"]]
            df.columns = ["Email", "Actif", "Inscrit le"]
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Aucun abonné pour le moment.")

    st.markdown("---")

    # ── Run logs ──────────────────────────────────────────────────────────────
    st.markdown("### 📋 Historique des runs")
    if RunLogDB:
        logs = RunLogDB.get_recent(limit=10)
        if logs:
            import pandas as pd
            df_log = pd.DataFrame(logs)
            df_log = df_log[["run_id", "timestamp", "prospect_count",
                              "sent_count", "status", "error"]]
            df_log.columns = ["Run ID", "Date", "Prospects", "Envoyés", "Statut", "Erreur"]
            st.dataframe(df_log, use_container_width=True)
        else:
            st.info("Aucun run enregistré.")
