"""
Newsletter Generator — builds a rich HTML newsletter with:
  - 5 top HNWI/UHNWI prospects with sales-ready summaries
  - Source links
  - Plotly comparative chart (potential vs urgency) embedded as base64 PNG
"""

from __future__ import annotations

import base64
import io
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    logger.warning("plotly not installed — chart will be skipped")

from backend.processors.scorer import ScoredProspect

# ─── Colour palette ───────────────────────────────────────────────────────────

COLORS = {
    "primary": "#1A3C5E",       # deep navy
    "accent": "#C9A84C",        # gold
    "bg": "#F8F9FA",
    "white": "#FFFFFF",
    "text": "#2C3E50",
    "muted": "#6C757D",
    "border": "#DEE2E6",
    "success": "#28A745",
    "warning": "#FFC107",
    "danger": "#DC3545",
}

EVENT_BADGE_COLORS = {
    "IPO": ("#1A3C5E", "#E8F0F8"),
    "M&A": ("#5E1A3C", "#F8E8F0"),
    "Fundraising": ("#1A5E3C", "#E8F8F0"),
    "Exit": ("#C9A84C", "#FDF8E8"),
    "Appointment": ("#5E3C1A", "#F8F0E8"),
    "Other": ("#4A4A4A", "#F0F0F0"),
}


def _event_badge(event_type: str) -> str:
    text_color, bg_color = EVENT_BADGE_COLORS.get(event_type, ("#4A4A4A", "#F0F0F0"))
    return (
        f'<span style="background:{bg_color};color:{text_color};'
        f'padding:3px 10px;border-radius:12px;font-size:11px;'
        f'font-weight:700;letter-spacing:0.5px;">'
        f'{event_type}</span>'
    )


def _score_bar(score: int, label: str = "Potentiel") -> str:
    """Render a mini progress bar for the score."""
    if score >= 80:
        color = COLORS["success"]
    elif score >= 60:
        color = COLORS["accent"]
    else:
        color = COLORS["muted"]

    return f"""
    <div style="margin:6px 0;">
      <div style="display:flex;justify-content:space-between;
                  font-size:11px;color:{COLORS['muted']};margin-bottom:3px;">
        <span>{label}</span><span style="font-weight:700;color:{color};">{score}/100</span>
      </div>
      <div style="background:#E9ECEF;border-radius:4px;height:6px;overflow:hidden;">
        <div style="background:{color};width:{score}%;height:100%;
                    border-radius:4px;"></div>
      </div>
    </div>"""


def _urgency_dots(urgency: int) -> str:
    """Render urgency as filled/empty dots (0–10 → 0–5 dots scale)."""
    dots_total = 5
    filled = round(urgency / 2)
    filled = max(0, min(dots_total, filled))
    dots_html = ""
    for i in range(dots_total):
        color = COLORS["danger"] if i < filled else "#DEE2E6"
        dots_html += f'<span style="color:{color};font-size:14px;">●</span> '
    return f'<span title="Urgence: {urgency}/10">{dots_html}</span>'


def generate_chart(prospects: list[ScoredProspect]) -> Optional[str]:
    """
    Generate a Plotly bar chart comparing potential score vs urgency for each prospect.
    Returns base64-encoded PNG string, or None if plotly is unavailable.
    """
    if not PLOTLY_AVAILABLE:
        return None

    try:
        names = [p.name.split(" ")[0] + " " + (p.name.split(" ")[-1] if len(p.name.split()) > 1 else "") for p in prospects]
        # Truncate long names
        names = [n[:18] + "…" if len(n) > 18 else n for n in names]
        potential_scores = [p.potential_score for p in prospects]
        urgency_scores = [p.urgency_score * 10 for p in prospects]  # scale to 100

        fig = go.Figure()

        fig.add_trace(go.Bar(
            name="Potentiel Wealth",
            x=names,
            y=potential_scores,
            marker_color=COLORS["primary"],
            marker_line_color=COLORS["accent"],
            marker_line_width=1.5,
            text=[f"{s}" for s in potential_scores],
            textposition="outside",
            textfont=dict(size=11, color=COLORS["text"]),
        ))

        fig.add_trace(go.Bar(
            name="Urgence × 10",
            x=names,
            y=urgency_scores,
            marker_color=COLORS["accent"],
            marker_line_color=COLORS["primary"],
            marker_line_width=1.5,
            text=[f"{s}" for s in urgency_scores],
            textposition="outside",
            textfont=dict(size=11, color=COLORS["text"]),
        ))

        fig.update_layout(
            title=dict(
                text="Comparatif Prospects : Potentiel vs Urgence",
                font=dict(size=14, color=COLORS["text"], family="Arial, sans-serif"),
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
            width=680,
            xaxis=dict(
                tickfont=dict(size=11),
                showgrid=False,
            ),
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
        event_badge = _event_badge(prospect.event_type)
        score_bar = _score_bar(prospect.potential_score)
        urgency_dots = _urgency_dots(prospect.urgency_score)

        rank_color = COLORS["accent"] if rank == 1 else (COLORS["primary"] if rank <= 3 else COLORS["muted"])

        cards_html += f"""
        <tr>
          <td style="padding:20px 0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="background:{COLORS['white']};border-radius:8px;
                          border:1px solid {COLORS['border']};
                          box-shadow:0 2px 8px rgba(0,0,0,0.05);">
              <tr>
                <!-- Rank badge -->
                <td width="60" style="padding:20px;vertical-align:top;text-align:center;">
                  <div style="width:40px;height:40px;border-radius:50%;
                              background:{rank_color};color:white;
                              font-size:18px;font-weight:800;line-height:40px;
                              text-align:center;margin:0 auto;">
                    {rank}
                  </div>
                </td>
                <!-- Main content -->
                <td style="padding:20px 20px 20px 0;vertical-align:top;">
                  <table width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                      <td>
                        <!-- Header: name + badge -->
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                          <tr>
                            <td>
                              <span style="font-size:18px;font-weight:800;
                                           color:{COLORS['text']};">
                                {prospect.name}
                              </span>
                              &nbsp;&nbsp;{event_badge}
                            </td>
                          </tr>
                        </table>
                        <!-- Title + company + location -->
                        <p style="margin:4px 0 12px;font-size:13px;color:{COLORS['muted']};">
                          {prospect.data.title} — <strong>{prospect.company}</strong>
                          &nbsp;·&nbsp; {prospect.data.location}
                          &nbsp;·&nbsp; <strong style="color:{COLORS['accent']}">
                            {prospect.amount_label}
                          </strong>
                        </p>
                        <!-- Event summary -->
                        <p style="margin:0 0 12px;font-size:14px;
                                  color:{COLORS['text']};line-height:1.6;">
                          {prospect.data.event_summary}
                        </p>
                        <!-- Sales pitch box -->
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                          <tr>
                            <td style="background:#F0F4F8;border-left:4px solid {COLORS['accent']};
                                       padding:12px 16px;border-radius:0 6px 6px 0;">
                              <p style="margin:0;font-size:13px;color:{COLORS['primary']};
                                        font-style:italic;line-height:1.6;">
                                <strong style="font-style:normal;
                                               color:{COLORS['accent']};">
                                  💡 Sales Insight:
                                </strong>
                                &nbsp;{prospect.sales_pitch}
                              </p>
                            </td>
                          </tr>
                        </table>
                        <!-- Scores row -->
                        <table width="100%" cellpadding="0" cellspacing="0" border="0"
                               style="margin-top:14px;">
                          <tr>
                            <td width="50%" style="padding-right:16px;vertical-align:top;">
                              {score_bar}
                            </td>
                            <td width="50%" style="vertical-align:top;">
                              <div style="font-size:11px;color:{COLORS['muted']};margin-bottom:3px;">
                                Urgence
                              </div>
                              {urgency_dots}
                            </td>
                          </tr>
                        </table>
                        <!-- Source link -->
                        <p style="margin:10px 0 0;font-size:12px;">
                          <a href="{prospect.source_url}"
                             style="color:{COLORS['primary']};text-decoration:none;
                                    border-bottom:1px solid {COLORS['accent']};">
                            🔗 Voir la source
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

    # ── Chart section ─────────────────────────────────────────────────────────
    if chart_b64:
        chart_section = f"""
        <tr>
          <td style="padding:20px 0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="background:{COLORS['white']};border-radius:8px;
                          border:1px solid {COLORS['border']};
                          padding:20px;">
              <tr>
                <td style="text-align:center;">
                  <h3 style="margin:0 0 16px;font-size:15px;color:{COLORS['text']};">
                    Analyse comparative — Top 5 Prospects
                  </h3>
                  <img src="data:image/png;base64,{chart_b64}"
                       alt="Comparatif Prospects"
                       style="max-width:100%;border-radius:6px;" />
                </td>
              </tr>
            </table>
          </td>
        </tr>"""
    else:
        chart_section = ""

    # ── Full HTML template ────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HNWI Prospect Intelligence — {date_str}</title>
</head>
<body style="margin:0;padding:0;background:{COLORS['bg']};
             font-family:Arial,Helvetica,sans-serif;">
  <!-- Outer wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:{COLORS['bg']};padding:20px 0;">
    <tr>
      <td>
        <!-- Container -->
        <table width="680" cellpadding="0" cellspacing="0" border="0"
               align="center" style="max-width:680px;width:100%;">

          <!-- ── HEADER ── -->
          <tr>
            <td style="background:{COLORS['primary']};border-radius:10px 10px 0 0;
                       padding:30px 36px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td>
                    <p style="margin:0;font-size:11px;color:{COLORS['accent']};
                               letter-spacing:2px;font-weight:700;
                               text-transform:uppercase;">
                      HNWI PROSPECT INTELLIGENCE
                    </p>
                    <h1 style="margin:6px 0 4px;font-size:24px;color:white;font-weight:800;">
                      Top 5 Prospects du Jour
                    </h1>
                    <p style="margin:0;font-size:13px;color:rgba(255,255,255,0.7);">
                      {date_str} · Détecté via signaux publics (IPO, M&A, Levées de fonds)
                    </p>
                  </td>
                  <td align="right" style="vertical-align:middle;">
                    <div style="background:{COLORS['accent']};border-radius:50%;
                                width:52px;height:52px;text-align:center;line-height:52px;
                                font-size:24px;">💎</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- ── INTRO BAND ── -->
          <tr>
            <td style="background:{COLORS['accent']};padding:12px 36px;">
              <p style="margin:0;font-size:13px;color:{COLORS['primary']};font-weight:600;">
                {len(prospects)} prospects qualifiés détectés aujourd'hui —
                tous présentent des signaux de liquidité récents.
              </p>
            </td>
          </tr>

          <!-- ── BODY ── -->
          <tr>
            <td style="background:{COLORS['bg']};padding:20px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">

                <!-- Prospect cards -->
                {cards_html}

                <!-- Chart -->
                {chart_section}

              </table>
            </td>
          </tr>

          <!-- ── FOOTER ── -->
          <tr>
            <td style="background:{COLORS['primary']};border-radius:0 0 10px 10px;
                       padding:24px 36px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td>
                    <p style="margin:0 0 8px;font-size:12px;
                               color:rgba(255,255,255,0.6);line-height:1.6;">
                      Cette newsletter est générée automatiquement à partir de sources publiques.
                      Les informations sont fournies à titre indicatif.
                      Veuillez vérifier les données avant tout contact commercial.
                    </p>
                    <p style="margin:0;font-size:11px;color:{COLORS['accent']};">
                      HNWI Prospect Intelligence · Powered by AI
                    </p>
                  </td>
                  <td align="right" style="vertical-align:bottom;">
                    <a href="{{{{ unsubscribe_url }}}}"
                       style="font-size:11px;color:rgba(255,255,255,0.5);
                              text-decoration:underline;">
                      Se désabonner
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
