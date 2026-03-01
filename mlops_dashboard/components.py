"""Reusable UI components for the MLOps dashboard."""

from datetime import datetime, timezone

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# Plotly shared layout
# ---------------------------------------------------------------------------

PLOTLY_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, sans-serif", color="#FAFAFA"),
    margin=dict(l=40, r=40, t=40, b=40),
)

COLORS = {
    "green": "#00C851",
    "yellow": "#ffbb33",
    "red": "#ff4444",
    "gray": "#6c757d",
    "blue": "#33b5e5",
    "purple": "#aa66cc",
    "orange": "#ff8800",
    "teal": "#00BFA5",
}

AGENT_COLORS = {
    "thesis_lord": COLORS["purple"],
    "edge": COLORS["green"],
    "ml_trainer": COLORS["blue"],
    "github": COLORS["gray"],
    "heston_cal": COLORS["orange"],
    "vol_slayer": COLORS["teal"],
    "deep_hedge": COLORS["yellow"],
    "post_mortem": COLORS["red"],
    "claude": COLORS["green"],
}

STATUS_COLORS = {
    "proposed": COLORS["blue"],
    "backtesting": COLORS["yellow"],
    "paper_live": COLORS["green"],
    "killed": COLORS["red"],
    "retired": COLORS["gray"],
}


# ---------------------------------------------------------------------------
# Health badges
# ---------------------------------------------------------------------------

def determine_model_health(row: pd.Series | None, max_age_days: int = 14) -> str:
    """Derive health status from a model row."""
    if row is None or (isinstance(row, pd.Series) and row.empty):
        return "no_data"
    is_active = row.get("is_active", False) if isinstance(row, dict) else row.get("is_active", False)
    if not is_active:
        return "inactive"
    trained_at = row.get("trained_at") if isinstance(row, dict) else row.get("trained_at")
    if trained_at:
        if hasattr(trained_at, "tzinfo") and trained_at.tzinfo is None:
            trained_at = trained_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - trained_at).days
        if age_days > max_age_days:
            return "stale"
    return "healthy"


def health_badge(status: str) -> str:
    """Return colored HTML badge for model health status."""
    colors = {
        "healthy": COLORS["green"],
        "stale": COLORS["yellow"],
        "inactive": COLORS["red"],
        "no_data": COLORS["gray"],
    }
    labels = {
        "healthy": "Healthy",
        "stale": "Stale",
        "inactive": "Inactive",
        "no_data": "No Data",
    }
    icons = {
        "healthy": "&#9679;",  # filled circle
        "stale": "&#9679;",
        "inactive": "&#9679;",
        "no_data": "&#9675;",  # empty circle
    }
    color = colors.get(status, COLORS["gray"])
    label = labels.get(status, status)
    icon = icons.get(status, "&#9679;")
    return (
        f'<span style="color:{color};font-weight:600;font-size:0.9rem;">'
        f'{icon} {label}</span>'
    )


# ---------------------------------------------------------------------------
# Empty states
# ---------------------------------------------------------------------------

def show_empty_state(message: str):
    """Display a contextual empty-state message."""
    st.info(message)


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def metric_row(metrics: list[dict]):
    """Render a row of st.metric cards."""
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        col.metric(label=m["label"], value=m["value"], delta=m.get("delta"))


def humanize_duration(seconds: float | None) -> str:
    """Convert seconds to a human-readable duration string."""
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def humanize_bytes(size_bytes: int | None) -> str:
    """Convert bytes to a human-readable size string."""
    if size_bytes is None:
        return "N/A"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def time_ago(dt) -> str:
    """Convert a datetime to a human-readable 'X ago' string."""
    if dt is None:
        return "Never"
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    seconds = delta.total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = int(seconds / 60)
        return f"{m}m ago"
    if seconds < 86400:
        h = int(seconds / 3600)
        return f"{h}h ago"
    d = int(seconds / 86400)
    return f"{d}d ago"


def extract_key_metric(model_type: str, metrics: dict | None) -> tuple[str, str]:
    """Extract the single most important metric for a model type. Returns (label, value)."""
    if not metrics:
        return ("Key Metric", "N/A")
    if model_type == "sentiment":
        val = metrics.get("direction_agreement")
        return ("Direction Agr.", f"{val:.1%}" if val else "N/A")
    if model_type == "signal_ranker":
        val = metrics.get("auc_roc")
        return ("AUC-ROC", f"{val:.3f}" if val else "N/A")
    if model_type == "deep_hedging":
        val = metrics.get("cvar_improvement_pct")
        if val:
            return ("CVaR Improv.", f"{val:.1f}%")
        val = metrics.get("final_cvar")
        return ("CVaR", f"{val:.4f}" if val else "N/A")
    return ("Metric", "N/A")
