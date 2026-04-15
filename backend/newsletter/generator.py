"""
Newsletter Generator — builds a rich HTML newsletter with:
  - 5 top HNWI/UHNWI prospects with sales-ready summaries
  - Source links
  - Plotly comparative chart (potential vs urgency) embedded as base64 PNG
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    logger.warning("plotly not installed — chart will be skipped")

from backend.processors.scorer import ScoredProspect

# ─── Société Générale colour palette ──────────────────────────────────────────

COLORS = {
    "primary":  "#E30613",   # SG rouge institutionnel
    "dark":     "#1A1A1A",   # Noir SG
    "bg":       "#F5F5F5",   # Fond clair
    "white":    "#FFFFFF",
    "text":     "#1A1A1A",
    "muted":    "#6B6B6B",
    "border":   "#E0E0E0",
    "success":  "#2E7D32",
    "warning":  "#E65100",
    "danger":   "#C62828",
    "accent":   "#B20010",   # Rouge SG foncé
}

EVENT_BADGE_COLORS = {
    "IPO":          ("#FFFFFF", "#E30613"),
    "M&A":          ("#FFFFFF", "#1A1A1A"),
    "Fundraising":  ("#B20010", "#FAE5E6"),
    "Exit":         ("#1A1A1A", "#EFEFEF"),
    "Appointment":  ("#FFFFFF", "#B20010"),
    "Other":        ("#6B6B6B", "#F0F0F0"),
}

# ─── SG logo : chargement de data/sg-logo.png (embarqué en base64) ──────────
# Fallback sur une marque HTML si le fichier est absent.

_LOGO_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sg-logo.png"

try:
    with open(_LOGO_PATH, "rb") as _f:
        _SG_LOGO_B64 = base64.b64encode(_f.read()).decode("utf-8")
    _SG_LOGO_IMG = (
        '<img src="data:image/png;base64,' + _SG_LOGO_B64 + '"'
        ' alt="Soci\u00e9t\u00e9 G\u00e9n\u00e9rale"'
        ' height="50" style="display:block;max-width:240px;" />'
    )
except Exception as _e:
    logger.warning("Logo SG introuvable (%s) — fallback logo textuel", _e)
    _SG_LOGO_IMG = (
        '<p style="margin:0;font-size:15px;font-weight:800;color:white;'
        'letter-spacing:2px;font-family:Arial,Helvetica,sans-serif;">'
        'SOCI\u00c9T\u00c9 G\u00c9N\u00c9RALE</p>'
    )


def _event_badge(event_type: str) -> str:
    text_color, bg_color = EVENT_BADGE_COLORS.get(event_type, ("#6B6B6B", "#F0F0F0"))
    return (
        f'<span style="background:{bg_color};color:{text_color};'
        f'padding:3px 10px;border-radius:2px;font-size:10px;'
        f'font-weight:700;letter-spacing:0.8px;text-transform:uppercase;">'
        f'{event_type}</span>'
    )


def _score_bar(score: int, label: str = "Potentiel: ") -> str:
    """Render a mini progress bar for the score."""
    if score >= 80:
        color = COLORS["success"]
    elif score >= 60:
        color = COLORS["primary"]
    else:
        color = COLORS["muted"]

    return f"""
    <div style="margin:6px 0;">
      <div style="display:flex;justify-content:space-between;
                  font-size:11px;color:{COLORS['muted']};margin-bottom:4px;
                  text-transform:uppercase;letter-spacing:0.5px;">
        <span>{label}</span>
        <span style="font-weight:700;color:{color};">{score}/100</span>
      </div>
      <div style="background:#E0E0E0;border-radius:2px;height:5px;overflow:hidden;">
        <div style="background:{color};width:{score}%;height:100%;border-radius:2px;"></div>
      </div>
    </div>"""


def _urgency_dots(urgency: int) -> str:
    """Render urgency as filled/empty circles (0–10 mapped to 0–5 dots)."""
    dots_total = 5
    filled = round(urgency / 2)
    filled = max(0, min(dots_total, filled))
    dots_html = ""
    for i in range(dots_total):
        color = COLORS["primary"] if i < filled else "#E0E0E0"
        dots_html += f'<span style="color:{color};font-size:13px;">&#9679;</span>'
    return f'<span title="Urgence: {urgency}/10" style="letter-spacing:2px;">{dots_html}</span>'


def generate_chart(prospects: list[ScoredProspect]) -> Optional[str]:
    """
    Generate a Plotly bar chart comparing potential score vs urgency for each prospect.
    Returns base64-encoded PNG string, or None if plotly is unavailable.
    """
    if not PLOTLY_AVAILABLE:
        return None

    try:
        names = [
            p.name.split(" ")[0] + " " + (p.name.split(" ")[-1] if len(p.name.split()) > 1 else "")
            for p in prospects
        ]
        names = [n[:18] + "…" if len(n) > 18 else n for n in names]
        potential_scores = [p.potential_score for p in prospects]
        urgency_scores   = [p.urgency_score * 10 for p in prospects]

        fig = go.Figure()

        fig.add_trace(go.Bar(
            name="Potentiel Wealth",
            x=names,
            y=potential_scores,
            marker_color=COLORS["primary"],
            marker_line_color=COLORS["dark"],
            marker_line_width=1,
            text=[f"{s}" for s in potential_scores],
            textposition="outside",
            textfont=dict(size=11, color=COLORS["text"]),
        ))

        fig.add_trace(go.Bar(
            name="Urgence × 10",
            x=names,
            y=urgency_scores,
            marker_color=COLORS["dark"],
            marker_line_color=COLORS["primary"],
            marker_line_width=1,
            text=[f"{s}" for s in urgency_scores],
            textposition="outside",
            textfont=dict(size=11, color=COLORS["text"]),
        ))

        fig.update_layout(
            title=dict(
                text="Comparatif Prospects : Potentiel vs Urgence",
                font=dict(size=13, color=COLORS["text"], family="Arial, sans-serif"),
                x=0.5,
            ),
            barmode="group",
            plot_bgcolor="white",
            paper_bgcolor="white",
            font=dict(family="Arial, sans-serif", color=COLORS["text"]),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(size=11),
            ),
            margin=dict(l=40, r=40, t=60, b=40),
            height=300,
            width=700,
            xaxis=dict(tickfont=dict(size=11), showgrid=False),
            yaxis=dict(
                range=[0, 115],
                tickfont=dict(size=10),
                gridcolor="#F0F0F0",
                title=dict(text="Score", font=dict(size=11)),
            ),
        )

        img_bytes = fig.to_image(format="png", scale=2)
        return base64.b64encode(img_bytes).decode("utf-8")

    except Exception as e:
        logger.warning(f"Chart generation failed: {e}")
        return None


def generate_newsletter_html(
    prospects: list[ScoredProspect],
    date: Optional[datetime] = None,
) -> str:
    """Build the complete HTML newsletter."""
    if date is None:
        date = datetime.now(timezone.utc)

    date_str = date.strftime("%A %d %B %Y")
    chart_b64 = generate_chart(prospects)

    # ── Prospect cards ────────────────────────────────────────────────────────
    cards_html = ""
    for rank, prospect in enumerate(prospects, start=1):
        event_badge  = _event_badge(prospect.event_type)
        score_bar    = _score_bar(prospect.potential_score)
        urgency_dots = _urgency_dots(prospect.urgency_score)

        if rank == 1:
            rank_color = COLORS["primary"]
        elif rank <= 3:
            rank_color = COLORS["accent"]
        else:
            rank_color = COLORS["muted"]

        cards_html += f"""
        <tr>
          <td style="padding:14px 0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="background:{COLORS['white']};
                          border:1px solid {COLORS['border']};
                          border-left:4px solid {rank_color};
                          border-radius:0 3px 3px 0;">
              <tr>
                <!-- Rank badge -->
                <td width="52" style="padding:20px 10px;vertical-align:top;text-align:center;">
                  <div style="width:34px;height:34px;border-radius:2px;
                              background:{rank_color};color:white;
                              font-size:15px;font-weight:800;line-height:34px;
                              text-align:center;margin:0 auto;
                              font-family:Arial,Helvetica,sans-serif;">
                    {rank}
                  </div>
                </td>
                <!-- Main content -->
                <td style="padding:20px 28px 20px 10px;vertical-align:top;">
                  <table width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                      <td>
                        <!-- Nom + badge événement -->
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                          <tr>
                            <td>
                              <span style="font-size:17px;font-weight:800;
                                           color:{COLORS['text']};
                                           font-family:Arial,Helvetica,sans-serif;">
                                {prospect.name}
                              </span>
                              &nbsp;&nbsp;{event_badge}
                            </td>
                          </tr>
                        </table>
                        <!-- Titre, société, lieu, montant -->
                        <p style="margin:6px 0 16px;font-size:13px;
                                  color:{COLORS['muted']};line-height:1.55;">
                          {prospect.data.title} &mdash;
                          <strong style="color:{COLORS['text']};">{prospect.company}</strong>
                          &nbsp;&middot;&nbsp;{prospect.data.location}
                          &nbsp;&middot;&nbsp;
                          <strong style="color:{COLORS['primary']};">{prospect.amount_label}</strong>
                        </p>
                        <!-- Résumé de l'événement -->
                        <p style="margin:0 0 18px;font-size:14px;
                                  color:{COLORS['text']};line-height:1.85;
                                  font-family:Arial,Helvetica,sans-serif;">
                          {prospect.data.event_summary}
                        </p>
                        <!-- Encart Sales Insight -->
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                          <tr>
                            <td style="background:#FBF5F5;
                                       border-left:4px solid {COLORS['primary']};
                                       padding:14px 20px;
                                       border-radius:0 3px 3px 0;">
                              <p style="margin:0 0 6px;font-size:10px;
                                        font-weight:700;letter-spacing:1px;
                                        text-transform:uppercase;
                                        color:{COLORS['primary']};">
                                Insight commercial
                              </p>
                              <p style="margin:0;font-size:13px;
                                        color:{COLORS['dark']};
                                        font-style:italic;line-height:1.8;
                                        font-family:Arial,Helvetica,sans-serif;">
                                {prospect.sales_pitch}
                              </p>
                            </td>
                          </tr>
                        </table>
                        <!-- Scores -->
                        <table width="100%" cellpadding="0" cellspacing="0" border="0"
                               style="margin-top:18px;">
                          <tr>
                            <td width="50%" style="padding-right:24px;vertical-align:top;">
                              {score_bar}
                            </td>
                            <td width="50%" style="vertical-align:top;">
                              <div style="font-size:10px;color:{COLORS['muted']};
                                          margin-bottom:5px;text-transform:uppercase;
                                          letter-spacing:0.8px;">
                                Urgence
                              </div>
                              {urgency_dots}
                            </td>
                          </tr>
                        </table>
                        <!-- Lien source -->
                        <p style="margin:14px 0 0;font-size:12px;
                                  border-top:1px solid {COLORS['border']};
                                  padding-top:12px;">
                          <a href="{prospect.source_url}"
                             style="color:{COLORS['primary']};text-decoration:none;
                                    font-weight:700;letter-spacing:0.3px;">
                            Consulter la source
                          </a>
                          &nbsp;&nbsp;
                          <span style="color:{COLORS['muted']};">
                            {prospect.data.sector}
                          </span>
                        </p>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""

    # ── Graphique comparatif ──────────────────────────────────────────────────
    if chart_b64:
        chart_section = f"""
        <tr>
          <td style="padding:14px 0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="background:{COLORS['white']};
                          border:1px solid {COLORS['border']};
                          border-radius:3px;
                          padding:24px;">
              <tr>
                <td style="text-align:center;">
                  <p style="margin:0 0 16px;font-size:11px;font-weight:700;
                              letter-spacing:1.5px;text-transform:uppercase;
                              color:{COLORS['muted']};">
                    Analyse comparative &mdash; Top 5 Prospects
                  </p>
                  <img src="data:image/png;base64,{chart_b64}"
                       alt="Comparatif Prospects"
                       style="max-width:100%;border-radius:3px;" />
                </td>
              </tr>
            </table>
          </td>
        </tr>"""
    else:
        chart_section = ""

    # ── Template HTML complet ─────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HNWI Prospect Intelligence &mdash; {date_str}</title>
</head>
<body style="margin:0;padding:0;background:{COLORS['bg']};
             font-family:Arial,Helvetica,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:{COLORS['bg']};padding:28px 0;">
    <tr>
      <td>
        <table width="700" cellpadding="0" cellspacing="0" border="0"
               align="center" style="max-width:700px;width:100%;">

          <!-- ── EN-TÊTE : fond rouge SG + logo ── -->
          <tr>
            <td style="background:{COLORS['primary']};
                       border-radius:4px 4px 0 0;
                       padding:26px 36px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="vertical-align:middle;">
                    {_SG_LOGO_IMG}
                  </td>
                  <td align="right" style="vertical-align:middle;">
                    <p style="margin:0 0 3px;font-size:10px;
                               color:rgba(255,255,255,0.65);
                               letter-spacing:1.5px;font-weight:600;
                               text-transform:uppercase;">
                      Prospect Intelligence
                    </p>
                    <p style="margin:0;font-size:13px;
                               color:rgba(255,255,255,0.9);font-weight:600;">
                      {date_str}
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- ── BANDEAU TITRE : fond noir SG ── -->
          <tr>
            <td style="background:{COLORS['dark']};padding:14px 36px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="vertical-align:middle;">
                    <h1 style="margin:0;font-size:20px;color:white;
                               font-weight:800;letter-spacing:0.5px;">
                      Top 5 Prospects - Sales Management
                    </h1>
                  </td>
                  <td align="right" style="vertical-align:middle;">
                    <span style="font-size:12px;color:rgba(255,255,255,0.55);">
                      IPO &middot; M&amp;A &middot; Levées de fonds
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- ── BANDEAU INTRO : rouge SG foncé ── -->
          <tr>
            <td style="background:{COLORS['accent']};padding:10px 36px;">
              <p style="margin:0;font-size:13px;color:white;font-weight:600;">
                {len(prospects)} prospect{'s' if len(prospects) > 1 else ''} qualifi{'és' if len(prospects) > 1 else 'é'} détect{'és' if len(prospects) > 1 else 'é'} aujourd'hui &mdash;
                tous présentent des signaux de liquidité récents.
              </p>
            </td>
          </tr>

          <!-- ── CORPS : cartes prospects ── -->
          <tr>
            <td style="background:{COLORS['bg']};padding:20px 18px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                {cards_html}
                {chart_section}
              </table>
            </td>
          </tr>

          <!-- ── PIED DE PAGE : fond noir SG + SGBP Luxembourg ── -->
          <tr>
            <td style="background:{COLORS['dark']};
                       border-radius:0 0 4px 4px;
                       padding:26px 36px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="vertical-align:top;">
                    <!-- Identité SGBP -->
                    <p style="margin:0 0 4px;font-size:13px;color:white;
                               font-weight:800;letter-spacing:0.5px;">
                      SGBP Luxembourg
                    </p>
                    <p style="margin:0 0 12px;font-size:11px;
                               color:rgba(255,255,255,0.55);">
                      Soci&eacute;t&eacute; G&eacute;n&eacute;rale Private Banking
                    </p>
                    <p style="margin:0 0 14px;font-size:11px;
                               color:rgba(255,255,255,0.4);line-height:1.7;">
                      Cette newsletter est g&eacute;n&eacute;r&eacute;e automatiquement &agrave; partir
                      de sources publiques. Les informations sont fournies &agrave; titre indicatif.
                      Veuillez v&eacute;rifier les donn&eacute;es avant tout contact commercial.
                    </p>
                    <p style="margin:0;font-size:10px;
                               color:rgba(255,255,255,0.25);
                               border-top:1px solid rgba(255,255,255,0.1);
                               padding-top:12px;letter-spacing:0.5px;">
                      HNWI Prospect Intelligence &middot; Powered by AI
                    </p>
                  </td>
                  <td align="right" style="vertical-align:top;padding-left:24px;width:120px;">
                    <!-- Mini marque SG dans le footer -->
                    <table cellpadding="0" cellspacing="4" border="0" align="right">
                      <tr>
                        <td style="width:18px;height:18px;background:{COLORS['primary']};
                                   border-radius:2px;font-size:0;line-height:0;">&nbsp;</td>
                        <td style="width:18px;height:18px;
                                   background:rgba(255,255,255,0.15);
                                   border-radius:2px;font-size:0;line-height:0;">&nbsp;</td>
                      </tr>
                      <tr>
                        <td style="width:18px;height:18px;
                                   background:rgba(255,255,255,0.15);
                                   border-radius:2px;font-size:0;line-height:0;">&nbsp;</td>
                        <td style="width:18px;height:18px;background:{COLORS['primary']};
                                   border-radius:2px;font-size:0;line-height:0;">&nbsp;</td>
                      </tr>
                    </table>
                    <br/><br/>
                    <a href="{{{{ unsubscribe_url }}}}"
                       style="font-size:11px;color:rgba(255,255,255,0.35);
                              text-decoration:underline;white-space:nowrap;">
                      Se d&eacute;sabonner
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""

    return html
