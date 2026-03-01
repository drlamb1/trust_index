"""System Pulse — health overview and activity feed.

Answers: "Is everything running? What happened recently?"
"""

from datetime import datetime, timezone

import streamlit as st

from components import (
    AGENT_COLORS,
    determine_model_health,
    extract_key_metric,
    health_badge,
    humanize_bytes,
    humanize_duration,
    metric_row,
    show_empty_state,
    time_ago,
)
from db import (
    get_active_models,
    get_backtest_summary,
    get_recent_simulation_logs,
    get_thesis_status_counts,
)

st.title("System Pulse")

# ---------------------------------------------------------------------------
# Model Health Cards
# ---------------------------------------------------------------------------
st.subheader("Model Health")

models_df = get_active_models()
model_types = ["sentiment", "signal_ranker", "deep_hedging"]
model_labels = {"sentiment": "FinBERT Sentiment", "signal_ranker": "XGBoost Signal Ranker", "deep_hedging": "Deep Hedging Policy"}

cols = st.columns(3)
for col, mt in zip(cols, model_types):
    with col:
        rows = models_df[models_df["model_type"] == mt] if not models_df.empty else None
        row = rows.iloc[0] if rows is not None and not rows.empty else None

        if row is not None:
            health = determine_model_health(row)
            badge = health_badge(health)
            metric_label, metric_val = extract_key_metric(mt, row.get("training_metrics"))
            trained = row.get("trained_at")

            st.markdown(f"### {model_labels[mt]}")
            st.markdown(f"**Status:** {badge}", unsafe_allow_html=True)
            st.markdown(f"**Version:** v{row['version']}")
            st.markdown(f"**Trained:** {time_ago(trained)}")
            st.markdown(f"**{metric_label}:** {metric_val}")
            st.markdown(f"**Size:** {humanize_bytes(row.get('model_size_bytes'))}")
            st.markdown(f"**Duration:** {humanize_duration(row.get('training_duration_seconds'))}")
        else:
            health = determine_model_health(None)
            badge = health_badge(health)
            st.markdown(f"### {model_labels[mt]}")
            st.markdown(f"**Status:** {badge}", unsafe_allow_html=True)
            st.caption("No trained model available")

# ---------------------------------------------------------------------------
# Summary Metrics
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Pipeline Summary")

thesis_counts = get_thesis_status_counts()
backtest_summary = get_backtest_summary()

total_theses = int(thesis_counts["count"].sum()) if not thesis_counts.empty else 0
active_models = len(models_df) if not models_df.empty else 0

avg_sharpe = "N/A"
avg_win_rate = "N/A"
if not backtest_summary.empty:
    s = backtest_summary.iloc[0]
    if s["avg_sharpe"] is not None:
        avg_sharpe = f"{s['avg_sharpe']:.3f}"
    if s["avg_win_rate"] is not None:
        avg_win_rate = f"{s['avg_win_rate']:.1%}"

metric_row([
    {"label": "Total Theses", "value": total_theses},
    {"label": "Active Models", "value": f"{active_models}/3"},
    {"label": "Avg Sharpe", "value": avg_sharpe},
    {"label": "Avg Win Rate", "value": avg_win_rate},
])

# ---------------------------------------------------------------------------
# Training Schedule
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Training Schedule")

now = datetime.now(timezone.utc)
weekday = now.weekday()  # 0=Mon, 6=Sun

# Calculate hours until next Sunday 2 AM UTC
days_until_sunday = (6 - weekday) % 7
if days_until_sunday == 0 and now.hour >= 4:
    days_until_sunday = 7
hours_until_sunday_2am = days_until_sunday * 24 + (2 - now.hour)
if hours_until_sunday_2am < 0:
    hours_until_sunday_2am += 7 * 24

schedule_cols = st.columns(4)
with schedule_cols[0]:
    st.markdown("**Sentiment**")
    st.caption(f"Sun 2:00 AM UTC")
    st.caption(f"~{hours_until_sunday_2am}h until next run")
with schedule_cols[1]:
    st.markdown("**Signal Ranker**")
    st.caption("Sun 3:00 AM UTC")
    st.caption(f"~{hours_until_sunday_2am + 1}h until next run")
with schedule_cols[2]:
    st.markdown("**Deep Hedging**")
    st.caption("Sun 4:00 AM UTC")
    st.caption(f"~{hours_until_sunday_2am + 2}h until next run")
with schedule_cols[3]:
    st.markdown("**Model Refresh**")
    st.caption("Hourly at :10")
    mins_until = (70 - now.minute) % 60
    st.caption(f"~{mins_until}m until next refresh")

# ---------------------------------------------------------------------------
# Recent Activity Feed
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Recent Activity")

hours_back = st.selectbox("Lookback", [6, 12, 24, 48, 72], index=2, format_func=lambda h: f"Last {h}h")
logs_df = get_recent_simulation_logs(hours_back)

if logs_df.empty:
    show_empty_state(
        f"No simulation events in the last {hours_back} hours. "
        "Events are created when theses are generated, backtested, or agents make decisions."
    )
else:
    # Agent filter
    agents = ["All"] + sorted(logs_df["agent_name"].unique().tolist())
    selected_agent = st.selectbox("Filter by agent", agents)

    filtered = logs_df if selected_agent == "All" else logs_df[logs_df["agent_name"] == selected_agent]

    # Build display table
    display = filtered[["created_at", "agent_name", "event_type", "thesis_id"]].copy()
    display["created_at"] = display["created_at"].apply(time_ago)
    display.columns = ["When", "Agent", "Event", "Thesis ID"]

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "When": st.column_config.TextColumn(width="small"),
            "Agent": st.column_config.TextColumn(width="small"),
            "Event": st.column_config.TextColumn(width="medium"),
            "Thesis ID": st.column_config.NumberColumn(width="small"),
        },
    )
    st.caption(f"Showing {len(filtered)} of {len(logs_df)} events")
