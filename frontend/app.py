"""
Streamlit Frontend — Prospect Intelligence
  - Email subscription form with daily newsletter option
  - Newsletter preview (latest run)
  - Dashboard: prospect table + Plotly chart
  - Admin: trigger pipeline, view run logs
"""

from __future__ import annotations

import base64
import os
import re
import sys

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

# ── Logo path (défini avant set_page_config pour l'icône de l'onglet) ─────────
_LOGO_PATH = ROOT / "data" / "sg-logo.png"

# ── Page config (doit être le premier appel Streamlit) ────────────────────────
st.set_page_config(
    page_title="Prospect Intelligence",
    page_icon=str(_LOGO_PATH) if _LOGO_PATH.exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Logo base64 pour intégration sidebar ──────────────────────────────────────
_LOGO_B64 = ""
if _LOGO_PATH.exists():
    with open(_LOGO_PATH, "rb") as _f:
        _LOGO_B64 = base64.b64encode(_f.read()).decode()

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Sidebar */
  [data-testid="stSidebar"] {
    background: #1A1A1A !important;
    border-right: 3px solid #E30613;
  }
  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] label,
  [data-testid="stSidebar"] div { color: rgba(255,255,255,0.82) !important; }
  [data-testid="stSidebar"] a   { color: #E30613 !important; }
  [data-testid="stSidebar"] hr  { border-color: rgba(255,255,255,0.12) !important; }

  /* Boutons principaux */
  .stButton > button,
  [data-testid="stFormSubmitButton"] > button {
    background: #E30613 !important;
    color: white !important;
    border: none !important;
    border-radius: 2px !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
  }
  .stButton > button:hover,
  [data-testid="stFormSubmitButton"] > button:hover {
    background: #B20010 !important;
    border: none !important;
  }

  /* Champs texte */
  .stTextInput input {
    border: 1px solid #E0E0E0 !important;
    border-radius: 2px !important;
  }
  .stTextInput input:focus {
    border-color: #E30613 !important;
    box-shadow: 0 0 0 2px rgba(227,6,19,0.08) !important;
  }

  /* Métriques */
  [data-testid="stMetric"] {
    background: white;
    border: 1px solid #E0E0E0;
    border-radius: 3px;
    padding: 16px !important;
  }
  [data-testid="stMetricValue"] { color: #1A1A1A !important; }
  [data-testid="stMetricLabel"] { color: #6B6B6B !important; font-size: 12px !important; }

  /* Séparateurs */
  hr { border-color: #E0E0E0 !important; margin: 1rem 0 !important; }
  .block-container { padding-top: 1.5rem !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _try_import_db():
    try:
        from backend.db.database import SubscriberDB, ProspectDB, RunLogDB
        return SubscriberDB, ProspectDB, RunLogDB
    except Exception:
        return None, None, None


def _email_valid(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def _send_latest_newsletter_to(email: str) -> tuple[bool, str]:
    """Reconstruit et envoie la dernière newsletter à une adresse unique."""
    try:
        from backend.processors.extractor import ProspectData
        from backend.processors.scorer import ScoredProspect
        from backend.newsletter.generator import generate_newsletter_html
        from backend.newsletter.sender import NewsletterSender

        _, ProspectDB_cls, _ = _try_import_db()
        if ProspectDB_cls is None:
            return False, "Base de données non disponible."

        run_id, records = ProspectDB_cls.get_latest_run()
        if not records:
            return False, "Aucune newsletter disponible pour le moment."

        prospects = []
        for r in records:
            pd = ProspectData(
                name=r["name"], title=r["title"], company=r["company"],
                sector=r["sector"], event_type=r["event_type"],
                event_summary=r["event_summary"],
                estimated_amount_usd=r.get("estimated_amount_usd"),
                amount_label=r["amount_label"], location=r["location"],
                source_url=r["source_url"], published_at=r.get("published_at"),
                sales_pitch=r["sales_pitch"], urgency_score=r["urgency_score"],
                confidence_score=r["confidence_score"],
            )
            prospects.append(ScoredProspect(
                data=pd,
                potential_score=r["potential_score"],
                urgency_score=r["urgency_score"],
                composite_rank=float(r["potential_score"]),
            ))

        html = generate_newsletter_html(prospects)  # date = aujourd'hui

        resend_key = os.getenv("RESEND_API_KEY", "").strip()
        if not resend_key:
            return False, "Clé RESEND_API_KEY absente — envoi impossible."

        sender = NewsletterSender()
        ok = sender.send_to_one(email, html)
        return (
            (True,  f"Newsletter du {run_id} envoyée avec succès.") if ok else
            (False, "Échec de l'envoi (vérifiez la configuration Resend).")
        )

    except Exception as exc:
        return False, f"Erreur : {exc}"


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # Logo SG sur fond blanc pour visibilité
    if _LOGO_B64:
        st.markdown(
            f'<div style="background:white;border-radius:3px;padding:8px 14px;'
            f'margin-bottom:14px;display:inline-block;">'
            f'<img src="data:image/png;base64,{_LOGO_B64}" '
            f'style="height:34px;display:block;" /></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<p style="margin:0 0 2px;font-size:10px;font-weight:700;'
        'letter-spacing:1.5px;text-transform:uppercase;color:#E30613 !important;">'
        'Prospect Intelligence</p>'
        '<p style="margin:0 0 14px;font-size:13px;color:rgba(255,255,255,0.55) !important;">'
        'HNWI &middot; UHNWI</p>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    page = st.radio(
        "Navigation",
        ["Accueil & Inscription", "Dashboard", "Apercu Newsletter", "Admin"],
        label_visibility="collapsed",
    )
    st.markdown("---")

    SubscriberDB, ProspectDB, RunLogDB = _try_import_db()
    if SubscriberDB:
        count = SubscriberDB.count_active()
        run_ids = ProspectDB.list_run_ids() if ProspectDB else []
        st.markdown(
            f'<p style="margin:4px 0;font-size:13px;">'
            f'<strong style="color:white !important;">{count}</strong> '
            f'<span style="color:rgba(255,255,255,0.5) !important;">abonné(s) actif(s)</span></p>',
            unsafe_allow_html=True,
        )
        if run_ids:
            st.markdown(
                f'<p style="margin:4px 0;font-size:12px;'
                f'color:rgba(255,255,255,0.4) !important;">'
                f'Dernière analyse : <strong style="color:rgba(255,255,255,0.7) !important;">'
                f'{run_ids[0]}</strong></p>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE : ACCUEIL & INSCRIPTION
# ─────────────────────────────────────────────────────────────────────────────
if "Accueil" in page:

    # ── Bandeau héro ──────────────────────────────────────────────────────────
    st.markdown("""
    <div style="background:linear-gradient(135deg,#E30613 0%,#8B000A 100%);
                border-radius:4px;padding:36px 40px;margin-bottom:28px;">
      <p style="margin:0 0 6px;font-size:10px;font-weight:700;
                color:rgba(255,255,255,0.55);letter-spacing:2px;text-transform:uppercase;">
        Prospect Intelligence
      </p>
      <h1 style="margin:0 0 10px;font-size:26px;font-weight:800;
                 color:white;letter-spacing:0.3px;">
        HNWI Prospect Intelligence
      </h1>
      <p style="margin:0 0 16px;color:rgba(255,255,255,0.85);
                font-size:15px;line-height:1.75;max-width:600px;">
        Détectez chaque jour les 5 meilleurs prospects HNWI/UHNWI via l'IA —
        IPO, M&amp;A, levées de fonds, nominations.
      </p>
      <p style="margin:0;font-size:11px;color:rgba(255,255,255,0.5);
                letter-spacing:1px;text-transform:uppercase;">
        Newsletter quotidienne &middot; Sales-ready &middot; Sources incluses
      </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Formulaire d'inscription ──────────────────────────────────────────────
    st.markdown("### Recevoir la newsletter")
    st.markdown(
        '<p style="color:#6B6B6B;font-size:14px;margin-bottom:4px;">'
        'Entrez votre adresse email pour recevoir la newsletter du jour. '
        'Cochez la case ci-dessous pour vous abonner aux envois quotidiens automatiques.</p>',
        unsafe_allow_html=True,
    )

    with st.form("subscribe_form", clear_on_submit=True):
        email_input = st.text_input(
            "Adresse email",
            placeholder="prenom.nom@societe.com",
        )
        daily_subscribe = st.checkbox(
            "M'abonner à la newsletter quotidienne (envoi automatique chaque matin à 7h UTC)",
            value=False,
        )
        submitted = st.form_submit_button(
            "S'inscrire et recevoir la newsletter du jour",
            use_container_width=True,
        )

        if submitted:
            email_clean = email_input.strip().lower()
            if not email_clean:
                st.error("Veuillez entrer votre adresse email.")
            elif not _email_valid(email_clean):
                st.error("Adresse email invalide. Veuillez vérifier le format.")
            elif SubscriberDB is None:
                st.warning("Base de données non disponible. Vérifiez la configuration.")
            else:
                # Gestion de l'abonnement quotidien
                if daily_subscribe:
                    added = SubscriberDB.add(email_clean)
                    if added:
                        sub_msg = f"{email_clean} abonné(e) à la newsletter quotidienne."
                    else:
                        SubscriberDB.set_active(email_clean, True)
                        sub_msg = f"{email_clean} : abonnement quotidien confirmé."
                else:
                    sub_msg = "Envoi unique — aucun abonnement quotidien enregistré."

                # Envoi de la newsletter du jour dans tous les cas
                ok, send_msg = _send_latest_newsletter_to(email_clean)
                if ok:
                    st.success(f"{sub_msg} {send_msg}")
                else:
                    st.info(sub_msg)
                    st.warning(f"Newsletter du jour non envoyée : {send_msg}")

    # ── Se désabonner ─────────────────────────────────────────────────────────
    with st.expander("Se désabonner"):
        with st.form("unsubscribe_form", clear_on_submit=True):
            unsub_email = st.text_input(
                "Adresse email à désabonner",
                placeholder="votre@email.com",
            )
            unsub_btn = st.form_submit_button("Se désabonner")
            if unsub_btn and unsub_email:
                if SubscriberDB:
                    removed = SubscriberDB.remove(unsub_email.strip().lower())
                    if removed:
                        st.success("Adresse désabonnée avec succès.")
                    else:
                        st.warning("Adresse introuvable dans la base d'abonnés.")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE : DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
elif "Dashboard" in page:
    st.markdown("## Dashboard Prospects")

    if ProspectDB is None:
        st.warning("Base de données non disponible.")
        st.stop()

    run_ids = ProspectDB.list_run_ids()
    if not run_ids:
        st.info("Aucune analyse effectuée. Lancez le pipeline via l'onglet Admin.")
        st.stop()

    selected_run = st.selectbox("Sélectionner une analyse", run_ids, index=0)
    records = ProspectDB.get_run(selected_run)

    if not records:
        st.info("Aucun prospect pour cette date.")
        st.stop()

    # ── KPIs ──────────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    top = records[0] if records else {}
    avg_score = round(sum(r["potential_score"] for r in records) / len(records)) if records else 0
    total_amount = sum(r.get("estimated_amount_usd") or 0 for r in records)
    amount_label = (
        f"${total_amount/1e9:.1f}B" if total_amount >= 1e9 else
        f"${total_amount/1e6:.0f}M" if total_amount >= 1e6 else "N/A"
    )
    with c1: st.metric("Prospects détectés", len(records))
    with c2: st.metric("Score moyen", f"{avg_score}/100")
    with c3: st.metric("Top prospect", top.get("name", "—"))
    with c4: st.metric("Volume total estimé", amount_label)

    st.markdown("---")

    # ── Graphique ─────────────────────────────────────────────────────────────
    try:
        import plotly.graph_objects as go
        names = [
            r["name"].split()[0] + " " + (r["name"].split()[-1] if len(r["name"].split()) > 1 else "")
            for r in records
        ]
        names = [n[:18] + "…" if len(n) > 18 else n for n in names]
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Potentiel (0-100)",
            x=names,
            y=[r["potential_score"] for r in records],
            marker_color="#E30613",
            text=[r["potential_score"] for r in records],
            textposition="outside",
        ))
        fig.add_trace(go.Bar(
            name="Urgence (×10)",
            x=names,
            y=[r["urgency_score"] * 10 for r in records],
            marker_color="#1A1A1A",
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

    # ── Cartes prospects ──────────────────────────────────────────────────────
    EVENT_COLORS = {
        "IPO":         ("#FFFFFF", "#E30613"),
        "M&A":         ("#FFFFFF", "#1A1A1A"),
        "Fundraising": ("#B20010", "#FAE5E6"),
        "Exit":        ("#1A1A1A", "#EFEFEF"),
        "Appointment": ("#FFFFFF", "#B20010"),
        "Other":       ("#6B6B6B", "#F0F0F0"),
    }

    for r in records:
        txt_c, bg_c = EVENT_COLORS.get(r["event_type"], ("#6B6B6B", "#F0F0F0"))
        badge_html = (
            f'<span style="background:{bg_c};color:{txt_c};padding:2px 8px;'
            f'border-radius:2px;font-size:10px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.5px;">'
            f'{r["event_type"]}</span>'
        )
        rank_c = "#E30613" if r["rank"] == 1 else ("#B20010" if r["rank"] <= 3 else "#6B6B6B")

        with st.container():
            col_rank, col_main, col_score = st.columns([1, 6, 2])
            with col_rank:
                st.markdown(
                    f'<div style="text-align:center;font-size:28px;font-weight:800;'
                    f'color:{rank_c};">{r["rank"]}</div>',
                    unsafe_allow_html=True,
                )
            with col_main:
                st.markdown(
                    f'**{r["name"]}** &nbsp; {badge_html} &nbsp; {r["company"]}',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<small style="color:#6B6B6B;">{r["title"]} &middot; {r["location"]}'
                    f' &middot; <strong style="color:#E30613;">{r["amount_label"]}</strong></small>',
                    unsafe_allow_html=True,
                )
                st.markdown(r["event_summary"])
                st.markdown(
                    f'<div style="background:#FBF5F5;border-left:4px solid #E30613;'
                    f'padding:10px 14px;border-radius:0 3px 3px 0;font-size:13px;color:#1A1A1A;">'
                    f'<strong style="font-size:10px;letter-spacing:1px;text-transform:uppercase;'
                    f'color:#E30613;">Insight commercial</strong><br/>'
                    f'<em>{r["sales_pitch"]}</em></div>',
                    unsafe_allow_html=True,
                )
                st.markdown(f'[Consulter la source]({r["source_url"]})')
            with col_score:
                st.metric("Score", f'{r["potential_score"]}/100')
                st.metric("Urgence", f'{r["urgency_score"]}/10')
        st.markdown("---")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE : APERCU NEWSLETTER
# ─────────────────────────────────────────────────────────────────────────────
elif "Apercu" in page:
    st.markdown("## Aperçu de la Dernière Newsletter")

    if ProspectDB is None:
        st.warning("Base de données non disponible.")
        st.stop()

    run_id, records = ProspectDB.get_latest_run()

    if not records:
        st.info("Aucune newsletter générée. Lancez le pipeline dans l'onglet Admin.")
        st.stop()

    st.success(f"Dernière analyse : **{run_id}** — {len(records)} prospects")

    try:
        from backend.processors.extractor import ProspectData
        from backend.processors.scorer import ScoredProspect
        from backend.newsletter.generator import generate_newsletter_html

        prospects_data = []
        for r in records:
            pd = ProspectData(
                name=r["name"], title=r["title"], company=r["company"],
                sector=r["sector"], event_type=r["event_type"],
                event_summary=r["event_summary"],
                estimated_amount_usd=r.get("estimated_amount_usd"),
                amount_label=r["amount_label"], location=r["location"],
                source_url=r["source_url"], published_at=r.get("published_at"),
                sales_pitch=r["sales_pitch"], urgency_score=r["urgency_score"],
                confidence_score=r["confidence_score"],
            )
            sp = ScoredProspect(
                data=pd,
                potential_score=r["potential_score"],
                urgency_score=r["urgency_score"],
                composite_rank=float(r["potential_score"]),
            )
            prospects_data.append(sp)

        html = generate_newsletter_html(prospects_data)  # date = aujourd'hui

        st.download_button(
            "Télécharger la newsletter HTML",
            data=html,
            file_name=f"newsletter_{run_id}.html",
            mime="text/html",
        )
        st.components.v1.html(html, height=900, scrolling=True)

    except Exception as e:
        st.error(f"Erreur lors de la génération de l'aperçu : {e}")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE : ADMIN
# ─────────────────────────────────────────────────────────────────────────────
elif "Admin" in page:
    st.markdown("## Administration")

    # ── Statut APIs ───────────────────────────────────────────────────────────
    st.markdown("### Configuration des APIs")
    api_cols = st.columns(3)
    for col, (key_name, label) in zip(api_cols, [
        ("ANTHROPIC_API_KEY", "Claude API"),
        ("TAVILY_API_KEY",    "Tavily Search"),
        ("RESEND_API_KEY",    "Resend Email"),
    ]):
        with col:
            val = os.getenv(key_name, "")
            ok  = bool(val)
            color  = "#2E7D32" if ok else "#C62828"
            status = "Configuré"  if ok else "Manquant"
            st.markdown(
                f'<div style="padding:14px;background:white;border-radius:3px;'
                f'border:1px solid #E0E0E0;border-left:4px solid {color};">'
                f'<strong style="font-size:13px;">{label}</strong><br/>'
                f'<span style="color:{color};font-size:12px;font-weight:600;">{status}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── Pipeline ──────────────────────────────────────────────────────────────
    st.markdown("### Lancer le Pipeline")
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**Dry Run** (sans envoi d'emails)")
        if st.button("Lancer le pipeline (dry run)", use_container_width=True):
            with st.spinner("Pipeline en cours..."):
                try:
                    from backend.pipeline import run_pipeline
                    result = run_pipeline(dry_run=True)
                    if result.success:
                        st.success(
                            f"Succès — {result.articles_collected} articles collectés, "
                            f"{result.articles_signaled} signalés, "
                            f"{result.prospects_ranked} prospects."
                        )
                    else:
                        st.error(f"Échec : {result.error}")
                except Exception as e:
                    st.error(f"Erreur : {e}")

    with col_b:
        st.markdown("**Email de test** (envoi à une seule adresse)")
        test_email_input = st.text_input(
            "Email de test", placeholder="test@example.com",
        )
        if st.button("Envoyer un email de test", use_container_width=True) and test_email_input:
            if not _email_valid(test_email_input):
                st.error("Adresse email invalide.")
            else:
                with st.spinner("Envoi en cours..."):
                    try:
                        from backend.pipeline import run_pipeline
                        result = run_pipeline(test_email=test_email_input.strip())
                        if result.success:
                            st.success(f"Email de test envoyé à {test_email_input}.")
                        else:
                            st.error(f"Échec : {result.error}")
                    except Exception as e:
                        st.error(f"Erreur : {e}")

    st.markdown("---")

    # ── Abonnés ───────────────────────────────────────────────────────────────
    st.markdown("### Abonnés")
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

    # ── Historique des runs ───────────────────────────────────────────────────
    st.markdown("### Historique des runs")
    if RunLogDB:
        logs = RunLogDB.get_recent(limit=10)
        if logs:
            import pandas as pd
            df_log = pd.DataFrame(logs)
            df_log = df_log[[
                "run_id", "timestamp", "prospect_count",
                "sent_count", "status", "error",
            ]]
            df_log.columns = ["Run ID", "Date", "Prospects", "Envoyés", "Statut", "Erreur"]
            st.dataframe(df_log, use_container_width=True)
        else:
            st.info("Aucun run enregistré.")
