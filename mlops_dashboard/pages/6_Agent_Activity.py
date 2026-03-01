"""Agent Activity — simulation log analytics.

Answers: "What are the agents doing? Is the simulation engine active?"
"""

import plotly.graph_objects as go
import streamlit as st

from components import (
    AGENT_COLORS,
    COLORS,
    PLOTLY_LAYOUT,
    metric_row,
    show_empty_state,
    time_ago,
)
from db import get_agent_activity, get_agent_memory_status

st.title("Agent Activity")

# ---------------------------------------------------------------------------
# Lookback selector
# ---------------------------------------------------------------------------
days = st.slider("Lookback (days)", min_value=1, max_value=30, value=7)
activity = get_agent_activity(days)

if activity.empty:
    show_empty_state(
        f"No simulation events in the last {days} days. "
        "Events are created when theses are generated, backtested, or agents make decisions."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Summary Metrics
# ---------------------------------------------------------------------------
total_events = len(activity)
distinct_agents = activity["agent_name"].nunique()
most_active = activity["agent_name"].value_counts().index[0]
top_event = activity["event_type"].value_counts().index[0]

metric_row([
    {"label": f"Events ({days}d)", "value": f"{total_events:,}"},
    {"label": "Active Agents", "value": distinct_agents},
    {"label": "Most Active", "value": most_active},
    {"label": "Top Event Type", "value": top_event.replace("_", " ").title()},
])

# ---------------------------------------------------------------------------
# Events by Agent
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Events by Agent")

agent_counts = activity["agent_name"].value_counts()
fig = go.Figure(go.Bar(
    x=agent_counts.index,
    y=agent_counts.values,
    marker_color=[AGENT_COLORS.get(a, COLORS["gray"]) for a in agent_counts.index],
))
fig.update_layout(**PLOTLY_LAYOUT, title=f"Event Counts by Agent (last {days}d)",
                  xaxis_title="Agent", yaxis_title="Events")
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Event Type Sunburst
# ---------------------------------------------------------------------------
st.subheader("Event Hierarchy")

grouped = activity.groupby(["agent_name", "event_type"]).size().reset_index(name="count")

labels = ["All Agents"]
parents = [""]
values = [total_events]
colors_list = [COLORS["gray"]]

for agent in grouped["agent_name"].unique():
    agent_total = int(grouped[grouped["agent_name"] == agent]["count"].sum())
    labels.append(agent)
    parents.append("All Agents")
    values.append(agent_total)
    colors_list.append(AGENT_COLORS.get(agent, COLORS["gray"]))

    agent_events = grouped[grouped["agent_name"] == agent]
    for _, row in agent_events.iterrows():
        labels.append(f"{row['event_type']}")
        parents.append(agent)
        values.append(int(row["count"]))
        colors_list.append(AGENT_COLORS.get(agent, COLORS["gray"]))

fig = go.Figure(go.Sunburst(
    labels=labels,
    parents=parents,
    values=values,
    marker=dict(colors=colors_list),
    branchvalues="total",
))
fig.update_layout(**PLOTLY_LAYOUT, title="Agent -> Event Type Hierarchy")
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Activity Timeline
# ---------------------------------------------------------------------------
st.subheader("Activity Timeline")

fig = go.Figure()
for agent in activity["agent_name"].unique():
    subset = activity[activity["agent_name"] == agent]
    fig.add_trace(go.Scatter(
        x=subset["created_at"],
        y=subset["agent_name"],
        mode="markers",
        name=agent,
        marker=dict(
            color=AGENT_COLORS.get(agent, COLORS["gray"]),
            size=8,
            opacity=0.7,
        ),
        text=subset["event_type"],
        hovertemplate="<b>%{y}</b><br>%{text}<br>%{x}<extra></extra>",
    ))

fig.update_layout(**PLOTLY_LAYOUT, title=f"Event Timeline (last {days}d)",
                  xaxis_title="Time", yaxis_title="Agent", showlegend=False)
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# PR Merge Activity
# ---------------------------------------------------------------------------
pr_merges = activity[activity["event_type"] == "pr_merge"]
if not pr_merges.empty:
    st.subheader("PR Merge Activity")

    display = pr_merges[["created_at", "event_data"]].copy()
    display["created_at"] = display["created_at"].apply(time_ago)

    pr_rows = []
    for _, row in display.iterrows():
        ed = row["event_data"]
        if isinstance(ed, dict):
            pr_rows.append({
                "When": row["created_at"],
                "PR": f"#{ed.get('pr_number', '?')}",
                "Title": ed.get("title", ""),
                "Author": ed.get("author", ""),
            })
    if pr_rows:
        import pandas as pd
        st.dataframe(pd.DataFrame(pr_rows), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Agent Memory Status
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Agent Memory")

memories = get_agent_memory_status()
if memories.empty:
    show_empty_state(
        "Agent memories not yet populated. The Post-Mortem Priest reviews "
        "simulation logs weekly and extracts durable insights (patterns, "
        "failures, successes)."
    )
else:
    st.dataframe(memories, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Raw Event Log (expandable)
# ---------------------------------------------------------------------------
with st.expander(f"Raw Event Log ({len(activity)} events)"):
    display = activity[["created_at", "agent_name", "event_type", "thesis_id"]].copy()
    display["created_at"] = display["created_at"].apply(time_ago)
    display.columns = ["When", "Agent", "Event", "Thesis ID"]
    st.dataframe(display, use_container_width=True, hide_index=True)
