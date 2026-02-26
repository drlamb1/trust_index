"""
EdgeFinder — FastAPI Web Application

Routes:
    GET /              → Daily briefing dashboard (HTML)
    GET /briefing      → Same
    GET /briefing.md   → Raw Markdown
    GET /health        → Health check (JSON)
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.dependencies import get_optional_user
from api.simulation_routes import router as simulation_router
from config.settings import settings
from core.models import User

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Briefing → structured HTML renderer
# ---------------------------------------------------------------------------


def _color_val(text: str) -> str:
    """Wrap positive/negative values in colored spans."""
    s = text.strip()
    if not s:
        return s
    # Detect arrows and +/- patterns
    if any(k in s for k in ("▲", "+")) and not s.startswith("-"):
        return f'<span class="val-up">{html.escape(s)}</span>'
    if any(k in s for k in ("▼", "-")) and "→" not in s:
        return f'<span class="val-dn">{html.escape(s)}</span>'
    return html.escape(s)


def _render_market_overview(lines: list[str]) -> str:
    """Render market overview as metric cards."""
    cards = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Parse: "  S&P 500            $  689.43  ▲ +0.72%"
        m = re.match(r"(.+?)\s{2,}\$?\s*([\d,.]+)\s+(.*)", line)
        if m:
            label, value, change = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            is_up = "▲" in change or (change.startswith("+") and "▼" not in change)
            is_dn = "▼" in change or (change.startswith("-") and "▲" not in change)
            cls = "up" if is_up else ("dn" if is_dn else "flat")
            arrow = "&#9650;" if is_up else ("&#9660;" if is_dn else "")
            cards.append(
                f'<div class="metric-card {cls}">'
                f'<div class="metric-label">{html.escape(label)}</div>'
                f'<div class="metric-value">{html.escape(value)}</div>'
                f'<div class="metric-change">{arrow} {html.escape(change.replace("▲","").replace("▼","").strip())}</div>'
                f'</div>'
            )
        else:
            cards.append(f'<div class="metric-card"><div class="metric-label">{html.escape(line)}</div></div>')
    return f'<div class="metrics-grid">{"".join(cards)}</div>'


def _render_movers(lines: list[str]) -> str:
    """Render watchlist movers as two-column tables."""
    gainers: list[str] = []
    losers: list[str] = []
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**Top Gainers"):
            current = gainers
            continue
        if stripped.startswith("**Top Losers"):
            current = losers
            continue
        if current is not None and stripped:
            current.append(stripped)

    def _mover_table(rows: list[str], title: str, cls: str) -> str:
        if not rows:
            return ""
        trs = []
        for row in rows:
            m = re.match(r"(\w+)\s+([+-]?\s*[\d.]+%)\s+\$([\d.]+)\s*→\s*\$([\d.]+)\s*\((\w+)\)", row)
            if m:
                sym, pct, old, new, period = m.groups()
                trs.append(
                    f'<tr><td class="sym">{sym}</td>'
                    f'<td class="pct {cls}">{pct.strip()}</td>'
                    f'<td class="price">${old} → ${new}</td></tr>'
                )
            else:
                trs.append(f'<tr><td colspan="3">{html.escape(row)}</td></tr>')
        return (
            f'<div class="movers-col">'
            f'<h4 class="movers-title {cls}">{title}</h4>'
            f'<table class="movers-table">{"".join(trs)}</table>'
            f'</div>'
        )

    return (
        f'<div class="movers-grid">'
        f'{_mover_table(gainers, "Top Gainers", "up")}'
        f'{_mover_table(losers, "Top Losers", "dn")}'
        f'</div>'
    )


def _render_drift(lines: list[str]) -> str:
    """Render 10-K drift as per-ticker cards."""
    cards = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        # First line: "[NVDA] 2025   Health 100  ▲ +10pts"
        m = re.match(r"\[(\w+)\]\s+(\d{4})\s+Health\s+(\d+)\s+(.*)", line)
        if m:
            sym, year, score, delta_str = m.groups()
            score_val = int(score)
            # Color the score
            if score_val >= 80:
                score_cls = "score-good"
            elif score_val >= 50:
                score_cls = "score-mid"
            else:
                score_cls = "score-bad"

            # Parse delta
            is_up = "▲" in delta_str
            is_dn = "▼" in delta_str
            delta_cls = "up" if is_up else ("dn" if is_dn else "flat")

            # Second line: details
            detail = ""
            if i + 1 < len(lines) and not lines[i + 1].strip().startswith("["):
                detail = lines[i + 1].strip()
                i += 1

            # Parse detail line for metrics
            detail_html = ""
            if detail:
                parts = [p.strip() for p in detail.split("|")]
                badges = []
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    # Color code metric changes
                    if re.search(r'\+\d+\.?\d*pp', part):
                        badges.append(f'<span class="badge badge-up">{html.escape(part)}</span>')
                    elif re.search(r'-\d+\.?\d*pp', part):
                        badges.append(f'<span class="badge badge-dn">{html.escape(part)}</span>')
                    elif "Flags" in part and ("++") in part:
                        badges.append(f'<span class="badge badge-dn">{html.escape(part)}</span>')
                    elif "RevGrowth" in part:
                        badges.append(f'<span class="badge badge-up">{html.escape(part)}</span>')
                    else:
                        badges.append(f'<span class="badge">{html.escape(part)}</span>')
                detail_html = f'<div class="drift-details">{"".join(badges)}</div>'

            cards.append(
                f'<div class="drift-card">'
                f'<div class="drift-header">'
                f'<span class="drift-sym">{sym}</span>'
                f'<span class="drift-year">{year}</span>'
                f'<span class="drift-score {score_cls}">{score}</span>'
                f'<span class="drift-delta {delta_cls}">{html.escape(delta_str.strip())}</span>'
                f'</div>'
                f'{detail_html}'
                f'</div>'
            )
        i += 1
    return f'<div class="drift-grid">{"".join(cards)}</div>'


def _render_placeholder(lines: list[str]) -> str:
    """Render a section with italic placeholder text."""
    text = "\n".join(l.strip() for l in lines if l.strip())
    if text.startswith("_") and text.endswith("_"):
        text = text[1:-1]
        return f'<p class="placeholder">{html.escape(text)}</p>'
    return f'<pre class="section-pre">{html.escape(text)}</pre>'


def _render_generic(lines: list[str]) -> str:
    """Render a section as styled pre block."""
    text = "\n".join(l.rstrip() for l in lines)
    return f'<pre class="section-pre">{html.escape(text.strip())}</pre>'


# Section config: emoji prefix → renderer
_SECTION_RENDERERS = {
    "MARKET OVERVIEW": _render_market_overview,
    "WATCHLIST MOVERS": _render_movers,
    "10-K DRIFT": _render_drift,
}


def _md_to_html(content_md: str) -> str:
    """Convert briefing markdown into structured HTML sections."""
    # Split into sections by ## headers
    sections: list[tuple[str, str, list[str]]] = []
    current_title = ""
    current_emoji = ""
    current_lines: list[str] = []

    for line in content_md.split("\n"):
        if line.startswith("## "):
            if current_title or current_lines:
                sections.append((current_emoji, current_title, current_lines))
            # Parse: "## 📊 MARKET OVERVIEW"
            header = line[3:].strip()
            # Extract emoji (first char or two)
            m = re.match(r"(\S+)\s+(.*)", header)
            if m:
                current_emoji = m.group(1)
                current_title = m.group(2)
            else:
                current_emoji = ""
                current_title = header
            current_lines = []
        elif line.startswith("═") or line.startswith("─"):
            continue  # Skip decorative borders
        elif line.strip().startswith("EDGEFINDER DAILY BRIEFING"):
            continue  # Skip the title (we render our own)
        elif line.strip().startswith("Generated "):
            continue  # Skip footer timestamp
        else:
            current_lines.append(line)

    if current_title or current_lines:
        sections.append((current_emoji, current_title, current_lines))

    # Render each section
    html_parts = []
    for emoji, title, lines in sections:
        if not title:
            continue  # Skip preamble

        # Choose renderer
        renderer = _render_generic
        for key, fn in _SECTION_RENDERERS.items():
            if key in title.upper():
                renderer = fn
                break

        # Check if it's a placeholder section
        stripped = [l.strip() for l in lines if l.strip()]
        if len(stripped) == 1 and stripped[0].startswith("_") and stripped[0].endswith("_"):
            content = _render_placeholder(stripped)
        elif not stripped:
            content = '<p class="placeholder">No data available.</p>'
        else:
            content = renderer(lines)

        html_parts.append(
            f'<section class="card">'
            f'<h3 class="card-title"><span class="card-emoji">{emoji}</span> {html.escape(title)}</h3>'
            f'{content}'
            f'</section>'
        )

    return "\n".join(html_parts)


# ---------------------------------------------------------------------------
# Full HTML page
# ---------------------------------------------------------------------------

_CSS = """
<style>
  :root {
    --bg:       #0b0e14;
    --surface:  #12151e;
    --border:   #1e2231;
    --text:     #c9d1d9;
    --text-dim: #525b6b;
    --accent:   #7c85f5;
    --up:       #3fb950;
    --dn:       #f85149;
    --flat:     #525b6b;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }

  /* Topbar */
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 24px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    position: sticky; top: 0; z-index: 10;
    backdrop-filter: blur(8px);
  }
  .topbar-brand {
    font-size: 13px; font-weight: 700;
    letter-spacing: 2.5px; text-transform: uppercase;
    color: var(--accent);
  }
  .topbar-date {
    font-size: 12px; color: var(--text-dim); font-weight: 400;
    margin-left: 16px; letter-spacing: 0.5px;
  }
  .topbar-actions { display: flex; gap: 16px; }
  .topbar-actions a {
    font-size: 11px; color: var(--text-dim);
    text-decoration: none; text-transform: uppercase;
    letter-spacing: 1px; font-weight: 500;
    transition: color 0.15s;
  }
  .topbar-actions a:hover { color: var(--accent); }

  /* Layout */
  .container { max-width: 920px; margin: 0 auto; padding: 24px 20px 80px; }

  /* Cards */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 16px;
  }
  .card-title {
    font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1.5px;
    color: var(--text-dim);
    margin-bottom: 16px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border);
  }
  .card-emoji { font-size: 14px; margin-right: 4px; }

  /* Value colors */
  .val-up, .up  { color: var(--up); }
  .val-dn, .dn  { color: var(--dn); }
  .flat          { color: var(--flat); }

  /* Market overview metric cards */
  .metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
  }
  .metric-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    text-align: center;
  }
  .metric-card.up { border-left: 3px solid var(--up); }
  .metric-card.dn { border-left: 3px solid var(--dn); }
  .metric-label {
    font-size: 11px; text-transform: uppercase;
    letter-spacing: 1px; color: var(--text-dim);
    margin-bottom: 6px;
  }
  .metric-value {
    font-size: 22px; font-weight: 600;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    color: var(--text);
  }
  .metric-change {
    font-size: 12px; font-weight: 500;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    margin-top: 4px;
  }

  /* Movers */
  .movers-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  @media (max-width: 640px) { .movers-grid { grid-template-columns: 1fr; } }
  .movers-title {
    font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px;
    margin-bottom: 10px;
    padding-left: 2px;
  }
  .movers-table {
    width: 100%;
    border-collapse: collapse;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 13px;
  }
  .movers-table td {
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  .movers-table tr:last-child td { border-bottom: none; }
  .movers-table .sym { font-weight: 600; color: var(--text); width: 60px; }
  .movers-table .pct { font-weight: 500; width: 70px; text-align: right; }
  .movers-table .price { color: var(--text-dim); font-size: 12px; text-align: right; }

  /* 10-K Drift */
  .drift-grid { display: flex; flex-direction: column; gap: 8px; }
  .drift-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
  }
  .drift-header {
    display: flex; align-items: center; gap: 12px;
    flex-wrap: wrap;
  }
  .drift-sym {
    font-size: 15px; font-weight: 700;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    color: var(--accent); min-width: 50px;
  }
  .drift-year {
    font-size: 11px; color: var(--text-dim);
    background: var(--border); border-radius: 4px;
    padding: 2px 8px;
  }
  .drift-score {
    font-size: 20px; font-weight: 700;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
  }
  .score-good { color: var(--up); }
  .score-mid  { color: #d29922; }
  .score-bad  { color: var(--dn); }
  .drift-delta {
    font-size: 13px; font-weight: 500;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
  }
  .drift-details {
    margin-top: 8px;
    display: flex; flex-wrap: wrap; gap: 6px;
  }
  .badge {
    font-size: 11px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    padding: 3px 8px;
    border-radius: 4px;
    background: var(--border);
    color: var(--text-dim);
  }
  .badge-up { background: #0d2818; color: var(--up); }
  .badge-dn { background: #2a1215; color: var(--dn); }

  /* Placeholder */
  .placeholder {
    font-size: 13px; color: var(--text-dim);
    font-style: italic; padding: 8px 0;
  }

  /* Generic pre sections */
  .section-pre {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 13px; line-height: 1.7;
    white-space: pre-wrap; word-break: break-word;
    color: var(--text); background: transparent;
    border: none; padding: 0; margin: 0;
  }

  /* Footer */
  .footer {
    font-size: 11px; color: var(--text-dim);
    text-align: center; padding-top: 32px;
    border-top: 1px solid var(--border);
    margin-top: 32px;
  }

  /* ---- Chat Panel ---- */
  .chat-toggle {
    font-size: 11px; color: var(--text-dim);
    text-transform: uppercase; letter-spacing: 1px;
    font-weight: 500; cursor: pointer;
    background: none; border: 1px solid var(--border);
    border-radius: 6px; padding: 5px 12px;
    transition: all 0.15s;
  }
  .chat-toggle:hover { color: var(--accent); border-color: var(--accent); }
  .chat-toggle.active { color: var(--accent); border-color: var(--accent); background: rgba(124,133,245,0.08); }

  .chat-overlay {
    position: fixed; top: 0; right: -420px; bottom: 0;
    width: 400px; max-width: 95vw;
    background: var(--surface);
    border-left: 1px solid var(--border);
    z-index: 100; display: flex; flex-direction: column;
    transition: right 0.25s ease;
    box-shadow: -4px 0 24px rgba(0,0,0,0.4);
  }
  .chat-overlay.open { right: 0; }

  .chat-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .chat-header-left { display: flex; align-items: center; gap: 8px; }
  .chat-persona-badge {
    font-size: 10px; font-weight: 700;
    width: 22px; height: 22px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 50%; color: #0b0e14;
  }
  .chat-persona-name {
    font-size: 12px; font-weight: 600;
    letter-spacing: 0.5px;
  }
  .chat-close {
    background: none; border: none; color: var(--text-dim);
    font-size: 18px; cursor: pointer; padding: 4px 8px;
    border-radius: 4px;
  }
  .chat-close:hover { color: var(--text); background: var(--border); }

  .chat-convos {
    display: flex; align-items: center; gap: 6px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .chat-convos select {
    flex: 1; font-size: 12px; background: var(--bg);
    color: var(--text); border: 1px solid var(--border);
    border-radius: 5px; padding: 5px 8px;
    font-family: inherit;
  }
  .chat-new-btn {
    font-size: 16px; background: none; border: 1px solid var(--border);
    color: var(--text-dim); border-radius: 5px; padding: 3px 10px;
    cursor: pointer;
  }
  .chat-new-btn:hover { color: var(--accent); border-color: var(--accent); }

  .chat-messages {
    flex: 1; overflow-y: auto; padding: 16px;
    display: flex; flex-direction: column; gap: 12px;
  }
  .chat-messages::-webkit-scrollbar { width: 6px; }
  .chat-messages::-webkit-scrollbar-track { background: transparent; }
  .chat-messages::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  .chat-msg {
    max-width: 92%;
    font-size: 13px; line-height: 1.55;
    padding: 10px 14px;
    border-radius: 10px;
    word-break: break-word;
  }
  .chat-msg.user {
    align-self: flex-end;
    background: rgba(124,133,245,0.12);
    border: 1px solid rgba(124,133,245,0.2);
    color: var(--text);
  }
  .chat-msg.assistant {
    align-self: flex-start;
    background: var(--bg);
    border: 1px solid var(--border);
  }
  .chat-msg .persona-tag {
    font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.8px;
    margin-bottom: 4px;
    display: block;
  }
  .chat-msg pre {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px; line-height: 1.5;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 6px; padding: 8px 10px;
    overflow-x: auto; margin: 6px 0;
    white-space: pre-wrap;
  }
  .chat-msg table {
    border-collapse: collapse; width: 100%; margin: 6px 0;
    font-family: 'JetBrains Mono', monospace; font-size: 11px;
  }
  .chat-msg table th, .chat-msg table td {
    border: 1px solid var(--border); padding: 4px 8px; text-align: left;
  }

  .chat-tool-card {
    font-size: 11px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin: 6px 0; padding: 8px 10px;
    cursor: pointer;
  }
  .chat-tool-card .tool-header {
    display: flex; align-items: center; gap: 6px;
    font-weight: 600; color: var(--accent);
  }
  .chat-tool-card .tool-spinner {
    width: 12px; height: 12px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .chat-tool-card .tool-result {
    display: none; margin-top: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px; line-height: 1.5;
    color: var(--text-dim);
    max-height: 120px; overflow-y: auto;
    white-space: pre-wrap;
  }
  .chat-tool-card.expanded .tool-result { display: block; }

  .chat-handoff {
    font-size: 11px; padding: 8px 12px;
    background: rgba(210,153,34,0.1);
    border: 1px solid rgba(210,153,34,0.3);
    border-radius: 6px; margin: 6px 0;
    cursor: pointer;
    color: #d29922;
  }
  .chat-handoff:hover { background: rgba(210,153,34,0.15); }

  .chat-input-area {
    padding: 12px 16px;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
  }
  .chat-persona-pills {
    display: flex; gap: 4px; margin-bottom: 8px;
  }
  .chat-pill {
    font-size: 10px; font-weight: 600;
    letter-spacing: 0.5px; text-transform: uppercase;
    padding: 4px 10px; border-radius: 12px;
    border: 1px solid var(--border);
    background: none; color: var(--text-dim);
    cursor: pointer; transition: all 0.15s;
  }
  .chat-pill:hover { border-color: var(--text-dim); color: var(--text); }
  .chat-pill.active { border-color: var(--accent); color: var(--accent); background: rgba(124,133,245,0.08); }
  .chat-pill[data-persona="analyst"].active { border-color: #7c85f5; color: #7c85f5; }
  .chat-pill[data-persona="thesis"].active { border-color: #d29922; color: #d29922; }
  .chat-pill[data-persona="pm"].active { border-color: #39d0b8; color: #39d0b8; }

  .chat-input-row {
    display: flex; gap: 8px; align-items: flex-end;
  }
  .chat-input {
    flex: 1; font-size: 13px;
    font-family: inherit;
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    resize: none;
    min-height: 40px; max-height: 120px;
    line-height: 1.4;
  }
  .chat-input:focus { outline: none; border-color: var(--accent); }
  .chat-input::placeholder { color: var(--text-dim); }
  .chat-send {
    background: var(--accent); color: #fff;
    border: none; border-radius: 8px;
    padding: 10px 14px; cursor: pointer;
    font-size: 13px; font-weight: 600;
    flex-shrink: 0;
    transition: opacity 0.15s;
  }
  .chat-send:hover { opacity: 0.85; }
  .chat-send:disabled { opacity: 0.4; cursor: not-allowed; }

  .chat-typing {
    font-size: 12px; color: var(--text-dim);
    font-style: italic; padding: 4px 0 0;
    min-height: 20px;
  }

  /* Adjust main container when chat is open */
  body.chat-open .container { margin-right: 400px; }
  @media (max-width: 1200px) { body.chat-open .container { margin-right: 0; } }
</style>
"""


def _login_page_html(error: str | None = None) -> str:
    """Render a minimal login page in the same dark theme as the dashboard."""
    error_html = ""
    if error:
        error_html = f'<div class="login-error">{html.escape(error)}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EdgeFinder — Login</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0b0e14; --surface: #12151e; --border: #1e2231;
      --text: #c9d1d9; --text-dim: #525b6b; --accent: #7c85f5;
      --dn: #f85149;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, sans-serif;
      background: var(--bg); color: var(--text);
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh;
    }}
    .login-card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 40px 36px; width: 360px; max-width: 90vw;
    }}
    .login-brand {{
      font-size: 13px; font-weight: 700; letter-spacing: 2.5px;
      text-transform: uppercase; color: var(--accent);
      text-align: center; margin-bottom: 24px;
    }}
    .login-error {{
      background: rgba(248,81,73,0.1); border: 1px solid rgba(248,81,73,0.3);
      color: var(--dn); font-size: 13px; padding: 8px 12px;
      border-radius: 6px; margin-bottom: 16px; text-align: center;
    }}
    label {{
      display: block; font-size: 11px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 1px;
      color: var(--text-dim); margin-bottom: 6px;
    }}
    input[type="email"], input[type="password"] {{
      width: 100%; font-size: 14px; font-family: inherit;
      background: var(--bg); color: var(--text);
      border: 1px solid var(--border); border-radius: 8px;
      padding: 10px 12px; margin-bottom: 16px;
    }}
    input:focus {{ outline: none; border-color: var(--accent); }}
    button {{
      width: 100%; background: var(--accent); color: #fff;
      border: none; border-radius: 8px; padding: 12px;
      font-size: 14px; font-weight: 600; cursor: pointer;
      transition: opacity 0.15s;
    }}
    button:hover {{ opacity: 0.85; }}
  </style>
</head>
<body>
  <div class="login-card">
    <div class="login-brand">EdgeFinder</div>
    {error_html}
    <form method="post" action="/login">
      <label for="email">Email</label>
      <input type="email" id="email" name="email" required autofocus>
      <label for="password">Password</label>
      <input type="password" id="password" name="password" required>
      <button type="submit">Sign In</button>
    </form>
  </div>
</body>
</html>"""


def _briefing_page(content_md: str, for_date: date | None = None, user: User | None = None) -> str:
    now = datetime.now(timezone.utc)
    for_date = for_date or date.today()
    date_display = for_date.strftime("%B %d, %Y")
    time_display = now.strftime("%H:%M UTC")

    body_html = _md_to_html(content_md)

    # User info for topbar
    user_html = ""
    if user:
        admin_link = '<a href="/admin">admin</a>' if user.role == "admin" else ""
        user_html = (
            f'{admin_link}'
            f'<a href="#" onclick="document.getElementById(\'pwModal\').style.display=\'flex\';return false">settings</a>'
            f'<span style="font-size:11px;color:var(--text-dim);margin-right:8px">'
            f'{html.escape(user.username)} ({user.role})</span>'
            f'<a href="/logout">logout</a>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EdgeFinder — {date_display}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  {_CSS}
</head>
<body>
  <nav class="topbar">
    <div>
      <span class="topbar-brand">EdgeFinder</span>
      <span class="topbar-date">{date_display}</span>
    </div>
    <div class="topbar-actions">
      <a href="/briefing.md">raw</a>
      <a href="/" onclick="location.reload(); return false;">refresh</a>
      <button class="chat-toggle" onclick="toggleChat()" id="chatToggle">Chat</button>
      {user_html}
    </div>
  </nav>
  <main class="container">
    {body_html}
    <div class="footer">Generated {time_display} by EdgeFinder</div>
  </main>

  <!-- Password Change Modal -->
  <div id="pwModal" style="position:fixed;inset:0;z-index:200;background:rgba(0,0,0,0.6);display:none;align-items:center;justify-content:center"
       onclick="if(event.target===this)this.style.display='none'">
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:32px;width:360px;max-width:90vw">
      <div style="font-size:14px;font-weight:600;margin-bottom:20px">Change Password</div>
      <label style="display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px">Current Password</label>
      <input type="password" id="pwCurrent" style="width:100%;font-size:14px;font-family:inherit;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:16px">
      <label style="display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px">New Password</label>
      <input type="password" id="pwNew" style="width:100%;font-size:14px;font-family:inherit;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:16px" placeholder="Minimum 8 characters">
      <div id="pwMsg" style="font-size:13px;margin-bottom:12px;display:none"></div>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button onclick="document.getElementById('pwModal').style.display='none'" style="background:none;color:var(--text-dim);border:1px solid var(--border);border-radius:8px;padding:10px 20px;font-size:13px;cursor:pointer;font-family:inherit">Cancel</button>
        <button onclick="changePw()" style="background:var(--accent);color:#fff;border:none;border-radius:8px;padding:10px 20px;font-size:13px;font-weight:600;cursor:pointer">Change Password</button>
      </div>
    </div>
  </div>
  <script>
  async function changePw(){{
    const msg=document.getElementById('pwMsg');
    const cur=document.getElementById('pwCurrent').value;
    const nw=document.getElementById('pwNew').value;
    if(nw.length<8){{msg.style.display='block';msg.style.color='var(--dn)';msg.textContent='Password must be at least 8 characters';return;}}
    try{{
      const r=await fetch('/api/auth/change-password',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{current_password:cur,new_password:nw}})}});
      const d=await r.json();
      if(!r.ok)throw new Error(d.detail||'Failed');
      msg.style.display='block';msg.style.color='var(--up)';msg.textContent='Password changed!';
      document.getElementById('pwCurrent').value='';document.getElementById('pwNew').value='';
      setTimeout(()=>{{document.getElementById('pwModal').style.display='none';msg.style.display='none';}},1500);
    }}catch(e){{msg.style.display='block';msg.style.color='var(--dn)';msg.textContent=e.message;}}
  }}
  </script>

  <!-- Chat Panel -->
  <aside class="chat-overlay" id="chatPanel">
    <div class="chat-header">
      <div class="chat-header-left">
        <div class="chat-persona-badge" id="chatBadge" style="background:#7c85f5">A</div>
        <span class="chat-persona-name" id="chatPersonaName">The Analyst</span>
      </div>
      <button class="chat-close" onclick="toggleChat()">&times;</button>
    </div>
    <div class="chat-convos">
      <select id="chatConvoSelect" onchange="loadConversation(this.value)">
        <option value="">New conversation</option>
      </select>
      <button class="chat-new-btn" onclick="newConversation()" title="New conversation">+</button>
    </div>
    <div class="chat-messages" id="chatMessages">
      <div class="chat-msg assistant">
        <span class="persona-tag" style="color:#7c85f5">The Analyst</span>
        Ready when you are. Ask me about your watchlist, filings, alerts, or any ticker.
      </div>
    </div>
    <div class="chat-input-area">
      <div class="chat-persona-pills">
        <button class="chat-pill active" data-persona="" onclick="setPersona(this,'')">Auto</button>
        <button class="chat-pill" data-persona="analyst" onclick="setPersona(this,'analyst')">Analyst</button>
        <button class="chat-pill" data-persona="thesis" onclick="setPersona(this,'thesis')">Thesis</button>
        <button class="chat-pill" data-persona="pm" onclick="setPersona(this,'pm')">PM</button>
      </div>
      <div class="chat-input-row">
        <textarea class="chat-input" id="chatInput" placeholder="Ask anything..." rows="1"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){{event.preventDefault();sendMessage()}}"></textarea>
        <button class="chat-send" id="chatSend" onclick="sendMessage()">&#9654;</button>
      </div>
      <div class="chat-typing" id="chatTyping"></div>
    </div>
  </aside>

  <script>
  // ---- Chat State ----
  const PERSONA_COLORS = {{analyst:'#7c85f5',thesis:'#d29922',pm:'#39d0b8'}};
  const PERSONA_NAMES = {{analyst:'The Analyst',thesis:'The Thesis Genius',pm:'The PM'}};
  const PERSONA_ICONS = {{analyst:'A',thesis:'T',pm:'P'}};
  let chatConversationId = null;
  let chatPersonaOverride = '';
  let chatBusy = false;

  function toggleChat() {{
    const p = document.getElementById('chatPanel');
    const t = document.getElementById('chatToggle');
    const open = p.classList.toggle('open');
    t.classList.toggle('active', open);
    document.body.classList.toggle('chat-open', open);
    if (open) {{
      loadConversations();
      document.getElementById('chatInput').focus();
    }}
  }}

  function setPersona(el, p) {{
    document.querySelectorAll('.chat-pill').forEach(b => b.classList.remove('active'));
    el.classList.add('active');
    chatPersonaOverride = p;
  }}

  function updatePersonaUI(name) {{
    const badge = document.getElementById('chatBadge');
    const label = document.getElementById('chatPersonaName');
    badge.textContent = PERSONA_ICONS[name] || 'A';
    badge.style.background = PERSONA_COLORS[name] || '#7c85f5';
    label.textContent = PERSONA_NAMES[name] || 'The Analyst';
    label.style.color = PERSONA_COLORS[name] || '#7c85f5';
  }}

  function newConversation() {{
    chatConversationId = null;
    const msgs = document.getElementById('chatMessages');
    msgs.innerHTML = '<div class="chat-msg assistant">' +
      '<span class="persona-tag" style="color:#7c85f5">The Analyst</span>' +
      'Ready when you are. Ask me about your watchlist, filings, alerts, or any ticker.</div>';
    updatePersonaUI('analyst');
    const sel = document.getElementById('chatConvoSelect');
    sel.value = '';
  }}

  async function loadConversations() {{
    try {{
      const r = await fetch('/api/chat/conversations');
      const d = await r.json();
      const sel = document.getElementById('chatConvoSelect');
      const cur = sel.value;
      sel.innerHTML = '<option value="">New conversation</option>';
      (d.conversations || []).forEach(c => {{
        const o = document.createElement('option');
        o.value = c.id;
        o.textContent = (c.title || 'Untitled').substring(0, 40);
        sel.appendChild(o);
      }});
      if (cur) sel.value = cur;
    }} catch(e) {{ console.error('loadConversations', e); }}
  }}

  async function loadConversation(id) {{
    if (!id) {{ newConversation(); return; }}
    chatConversationId = id;
    try {{
      const r = await fetch(`/api/chat/conversations/${{id}}/messages`);
      const d = await r.json();
      const msgs = document.getElementById('chatMessages');
      msgs.innerHTML = '';
      let lastPersona = 'analyst';
      (d.messages || []).forEach(m => {{
        if (m.role === 'user') {{
          appendUserMsg(m.content);
        }} else if (m.role === 'assistant' && m.content) {{
          lastPersona = m.persona || lastPersona;
          appendAssistantMsg(m.content, m.persona || 'analyst');
        }} else if (m.role === 'tool_call') {{
          appendToolCard(m.tool_name, m.tool_input, null, true);
        }} else if (m.role === 'tool_result') {{
          // Already handled by tool_call cards in live mode
        }}
      }});
      updatePersonaUI(lastPersona);
      scrollChat();
    }} catch(e) {{ console.error('loadConversation', e); }}
  }}

  function appendUserMsg(text) {{
    const msgs = document.getElementById('chatMessages');
    const div = document.createElement('div');
    div.className = 'chat-msg user';
    div.textContent = text;
    msgs.appendChild(div);
  }}

  function appendAssistantMsg(text, persona) {{
    const msgs = document.getElementById('chatMessages');
    const div = document.createElement('div');
    div.className = 'chat-msg assistant';
    const color = PERSONA_COLORS[persona] || '#7c85f5';
    const name = PERSONA_NAMES[persona] || 'The Analyst';
    div.innerHTML = '<span class="persona-tag" style="color:' + color + '">' + name + '</span>';
    // Simple markdown: bold, code blocks, inline code, tables, line breaks
    let html = escapeHtml(text);
    // Code blocks
    html = html.replace(/```([\\s\\S]*?)```/g, '<pre>$1</pre>');
    // Bold
    html = html.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code style="background:var(--border);padding:1px 4px;border-radius:3px;font-size:12px">$1</code>');
    // Tables (simple pipe tables)
    html = html.replace(/^(\\|.+\\|\\n?)+/gm, function(match) {{
      const rows = match.trim().split('\\n').filter(r => r.trim());
      if (rows.length < 2) return match;
      let t = '<table>';
      rows.forEach((row, i) => {{
        if (row.match(/^\\|[\\s-:|]+\\|$/)) return; // separator row
        const cells = row.split('|').filter((c,idx) => idx > 0 && idx < row.split('|').length - 1);
        const tag = i === 0 ? 'th' : 'td';
        t += '<tr>' + cells.map(c => `<${{tag}}>${{c.trim()}}</${{tag}}>`).join('') + '</tr>';
      }});
      t += '</table>';
      return t;
    }});
    // Line breaks
    html = html.replace(/\\n/g, '<br>');
    div.innerHTML += html;
    msgs.appendChild(div);
    return div;
  }}

  function appendToolCard(name, input, result, done) {{
    const msgs = document.getElementById('chatMessages');
    const card = document.createElement('div');
    card.className = 'chat-tool-card' + (done ? ' expanded' : '');
    card.id = 'tool-' + name + '-' + Date.now();
    card.onclick = function() {{ this.classList.toggle('expanded'); }};
    let header = '<div class="tool-header">';
    if (!done) header += '<div class="tool-spinner"></div>';
    header += '<span>' + escapeHtml(name.replace(/_/g, ' ')) + '</span></div>';
    let body = '';
    if (result) {{
      body = '<div class="tool-result">' + escapeHtml(JSON.stringify(result, null, 2)).substring(0, 500) + '</div>';
    }} else {{
      body = '<div class="tool-result">Running...</div>';
    }}
    card.innerHTML = header + body;
    msgs.appendChild(card);
    return card;
  }}

  function escapeHtml(t) {{
    const d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
  }}

  function scrollChat() {{
    const msgs = document.getElementById('chatMessages');
    msgs.scrollTop = msgs.scrollHeight;
  }}

  async function sendMessage() {{
    if (chatBusy) return;
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    if (!text) return;

    chatBusy = true;
    document.getElementById('chatSend').disabled = true;
    input.value = '';
    input.style.height = 'auto';

    appendUserMsg(text);
    scrollChat();

    const typing = document.getElementById('chatTyping');
    typing.textContent = 'Thinking...';

    let currentAssistantDiv = null;
    let currentAssistantText = '';
    let currentToolCard = null;

    try {{
      const resp = await fetch('/api/chat', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
          message: text,
          conversation_id: chatConversationId,
          persona: chatPersonaOverride || null,
        }}),
      }});

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {{
        const {{done, value}} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {{stream: true}});

        // Parse SSE events from buffer
        const lines = buffer.split('\\n');
        buffer = lines.pop() || '';  // keep incomplete line

        let eventType = '';
        let eventData = '';
        for (const line of lines) {{
          if (line.startsWith('event: ')) {{
            eventType = line.substring(7).trim();
          }} else if (line.startsWith('data: ')) {{
            eventData = line.substring(6);
            // Process event
            try {{
              const data = JSON.parse(eventData);
              handleSSE(eventType, data);
            }} catch(e) {{}}
            eventType = '';
            eventData = '';
          }}
        }}
      }}
    }} catch(e) {{
      typing.textContent = 'Error: ' + e.message;
      console.error('sendMessage', e);
    }}

    chatBusy = false;
    document.getElementById('chatSend').disabled = false;
    typing.textContent = '';
    scrollChat();
    loadConversations();

    // Track current assistant message for token streaming
    function handleSSE(type, data) {{
      switch(type) {{
        case 'meta':
          chatConversationId = data.conversation_id;
          updatePersonaUI(data.persona);
          typing.textContent = (data.display_name || 'Thinking') + '...';
          break;

        case 'token':
          if (!currentAssistantDiv) {{
            const msgs = document.getElementById('chatMessages');
            currentAssistantDiv = document.createElement('div');
            currentAssistantDiv.className = 'chat-msg assistant';
            const pName = data.persona || document.getElementById('chatPersonaName').textContent;
            const pColor = document.getElementById('chatBadge').style.background;
            currentAssistantDiv.innerHTML = '<span class="persona-tag" style="color:' + pColor + '">' + escapeHtml(pName) + '</span>';
            msgs.appendChild(currentAssistantDiv);
            currentAssistantText = '';
          }}
          currentAssistantText += data.text;
          // Render simple markdown as we stream
          let rendered = escapeHtml(currentAssistantText);
          rendered = rendered.replace(/```([\\s\\S]*?)```/g, '<pre>$1</pre>');
          rendered = rendered.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
          rendered = rendered.replace(/`([^`]+)`/g, '<code style="background:var(--border);padding:1px 4px;border-radius:3px;font-size:12px">$1</code>');
          rendered = rendered.replace(/\\n/g, '<br>');
          // Keep the persona tag, update only text content
          const tagEl = currentAssistantDiv.querySelector('.persona-tag');
          const tagHtml = tagEl ? tagEl.outerHTML : '';
          currentAssistantDiv.innerHTML = tagHtml + rendered;
          scrollChat();
          break;

        case 'tool_start':
          // End current text block
          currentAssistantDiv = null;
          currentAssistantText = '';
          typing.textContent = 'Running ' + data.tool_name.replace(/_/g, ' ') + '...';
          currentToolCard = appendToolCard(data.tool_name, null, null, false);
          scrollChat();
          break;

        case 'tool_result':
          if (currentToolCard) {{
            currentToolCard.classList.add('expanded');
            const spinner = currentToolCard.querySelector('.tool-spinner');
            if (spinner) spinner.remove();
            const resultDiv = currentToolCard.querySelector('.tool-result');
            if (resultDiv) {{
              resultDiv.textContent = JSON.stringify(data.result, null, 2).substring(0, 500);
            }}
          }}
          currentToolCard = null;
          typing.textContent = 'Thinking...';
          break;

        case 'handoff':
          const hDiv = document.createElement('div');
          hDiv.className = 'chat-handoff';
          const targetName = PERSONA_NAMES[data.target_persona] || data.target_persona;
          // If in Auto mode, auto-switch — the backend already updated active_persona,
          // so the next Auto-routed message will go to the right persona.
          // We just update the UI to show the new persona.
          if (!chatPersonaOverride) {{
            hDiv.textContent = 'Handing off to ' + targetName;
            updatePersonaUI(data.target_persona);
            // Don't set chatPersonaOverride — leave in Auto mode.
            // The engine's conv.active_persona handles the routing.
          }} else {{
            hDiv.textContent = 'Suggested: Switch to ' + targetName;
            hDiv.onclick = function() {{
              setPersona(
                document.querySelector('.chat-pill[data-persona="' + data.target_persona + '"]'),
                data.target_persona
              );
            }};
          }}
          if (data.reason) {{
            const reasonSpan = document.createElement('div');
            reasonSpan.style.cssText = 'font-size:10px;margin-top:4px;opacity:0.7;max-height:60px;overflow:hidden';
            reasonSpan.textContent = data.reason;
            hDiv.appendChild(reasonSpan);
          }}
          document.getElementById('chatMessages').appendChild(hDiv);
          scrollChat();
          break;

        case 'done':
          currentAssistantDiv = null;
          currentAssistantText = '';
          typing.textContent = '';
          break;

        case 'error':
          typing.textContent = 'Error: ' + (data.message || 'Unknown error');
          break;
      }}
    }}
  }}

  // Auto-resize textarea
  document.getElementById('chatInput').addEventListener('input', function() {{
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  }});
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="EdgeFinder",
        description="Market intelligence platform",
        version="0.6.0",
        docs_url="/api/docs",
        redoc_url=None,
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    from api.admin_routes import router as admin_router
    from api.auth_routes import router as auth_router
    from api.chat_routes import router as chat_router

    app.include_router(admin_router)
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(simulation_router)

    @app.on_event("startup")
    async def startup_warnings():
        if settings.secret_key == "change-me-in-production" and settings.is_production:
            logger.critical(
                "SECRET_KEY is using the default value in production! "
                "Set SECRET_KEY to a secure random value."
            )

    @app.get("/health")
    async def health() -> JSONResponse:
        from core.database import check_db_connection
        db_ok = await check_db_connection()
        return JSONResponse({"status": "ok" if db_ok else "degraded", "db": db_ok})

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        user = await _try_get_user(request)
        if user:
            return RedirectResponse("/", status_code=302)
        return HTMLResponse(_login_page_html())

    @app.post("/login", response_class=HTMLResponse)
    async def login_form(request: Request):
        """Handle login form submission (browser POST)."""
        from core.database import AsyncSessionLocal
        from core.security import create_access_token, verify_password

        form = await request.form()
        email = form.get("email", "")
        password = form.get("password", "")

        async with AsyncSessionLocal() as session:
            from sqlalchemy import select

            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()

        error = None
        if not user or not verify_password(str(password), user.hashed_password):
            error = "Invalid email or password"
        elif not user.is_active:
            error = "Account is deactivated"

        if error:
            return HTMLResponse(_login_page_html(error=error))

        token = create_access_token({"sub": str(user.id), "role": user.role})
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            key="ef_token",
            value=token,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=settings.access_token_expire_minutes * 60,
        )
        return response

    @app.get("/logout")
    async def logout_page():
        response = RedirectResponse("/login", status_code=302)
        response.delete_cookie(key="ef_token")
        return response

    @app.get("/", response_class=HTMLResponse)
    @app.get("/briefing", response_class=HTMLResponse)
    async def briefing_html(
        request: Request,
        date_str: str | None = Query(default=None, alias="date"),
        user: User | None = Depends(get_optional_user),
    ) -> HTMLResponse:
        # Require auth in production
        if settings.is_production and user is None:
            return RedirectResponse("/login", status_code=302)

        from core.database import AsyncSessionLocal
        from daily_briefing import generate_briefing

        for_date = date.fromisoformat(date_str) if date_str else None

        try:
            async with AsyncSessionLocal() as session:
                content_md = await generate_briefing(session, for_date=for_date)
        except Exception as exc:
            logger.exception("Briefing generation failed")
            content_md = f"Error generating briefing: {exc}"

        return HTMLResponse(_briefing_page(content_md, for_date, user=user))

    @app.get("/briefing.md", response_class=PlainTextResponse)
    async def briefing_md(
        request: Request,
        date_str: str | None = Query(default=None, alias="date"),
        user: User | None = Depends(get_optional_user),
    ) -> PlainTextResponse:
        if settings.is_production and user is None:
            return PlainTextResponse("Authentication required", status_code=401)

        from core.database import AsyncSessionLocal
        from daily_briefing import generate_briefing

        for_date = date.fromisoformat(date_str) if date_str else None

        async with AsyncSessionLocal() as session:
            content_md = await generate_briefing(session, for_date=for_date)

        return PlainTextResponse(content_md, media_type="text/plain; charset=utf-8")

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_panel(request: Request):
        user = await _try_get_user(request)
        if not user or user.role != "admin":
            return RedirectResponse("/login", status_code=302)
        from api.admin_page import admin_page_html
        return HTMLResponse(admin_page_html(
            current_user_id=user.id,
            current_username=user.username,
        ))

    return app


async def _try_get_user(request: Request) -> User | None:
    """Try to extract user from request without raising. Used in login page."""
    from core.database import AsyncSessionLocal

    from api.dependencies import _COOKIE_NAME
    from core.security import decode_access_token

    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == int(user_id), User.is_active.is_(True))
            )
            return result.scalar_one_or_none()
    except Exception:
        return None
