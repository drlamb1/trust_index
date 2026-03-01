"""Thesis Lifecycle — funnel, backtest analytics, and generator leaderboard.

Answers: "Is the thesis engine producing alpha?"
"""

import plotly.graph_objects as go
import streamlit as st

from components import COLORS, PLOTLY_LAYOUT, STATUS_COLORS, show_empty_state
from db import get_backtest_results, get_thesis_lifecycle_data

st.title("Thesis Lifecycle")

theses = get_thesis_lifecycle_data()
backtests = get_backtest_results()

if theses.empty:
    show_empty_state(
        "No theses generated yet. The Thesis Lord generates theses when "
        "signal convergences are detected (runs every 4 hours)."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Lifecycle Funnel
# ---------------------------------------------------------------------------
st.subheader("Lifecycle Funnel")

status_order = ["proposed", "backtesting", "paper_live", "killed", "retired"]
status_counts = theses["status"].value_counts()
funnel_values = [int(status_counts.get(s, 0)) for s in status_order]
funnel_labels = [s.replace("_", " ").title() for s in status_order]

col1, col2 = st.columns([2, 1])

with col1:
    fig = go.Figure(go.Funnel(
        y=funnel_labels,
        x=funnel_values,
        textinfo="value+percent initial",
        marker=dict(color=[STATUS_COLORS.get(s, COLORS["gray"]) for s in status_order]),
    ))
    fig.update_layout(**PLOTLY_LAYOUT, title="Thesis Lifecycle Funnel")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    # Status donut
    non_zero = [(s, c) for s, c in zip(status_order, funnel_values) if c > 0]
    if non_zero:
        labels, values = zip(*non_zero)
        fig = go.Figure(go.Pie(
            labels=[l.replace("_", " ").title() for l in labels],
            values=values,
            hole=0.5,
            marker=dict(colors=[STATUS_COLORS.get(s, COLORS["gray"]) for s in labels]),
        ))
        fig.update_layout(**PLOTLY_LAYOUT, title="Current Status", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Backtest Analytics
# ---------------------------------------------------------------------------
if backtests.empty:
    st.divider()
    show_empty_state("No backtest results yet. Backtests run automatically for proposed theses.")
    st.stop()

st.divider()
st.subheader("Backtest Performance")

col1, col2 = st.columns(2)

with col1:
    # Sharpe distribution
    fig = go.Figure()
    sharpe_vals = backtests["sharpe"].dropna()
    fig.add_trace(go.Histogram(
        x=sharpe_vals,
        nbinsx=30,
        marker_color=COLORS["blue"],
        opacity=0.8,
    ))
    fig.add_vline(x=0, line_dash="dash", line_color=COLORS["red"],
                  annotation_text="Break-even")
    fig.update_layout(**PLOTLY_LAYOUT, title="Sharpe Ratio Distribution",
                      xaxis_title="Sharpe", yaxis_title="Count")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    # Monte Carlo p-value distribution
    pvals = backtests["monte_carlo_p_value"].dropna()
    if not pvals.empty:
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=pvals,
            nbinsx=20,
            marker_color=COLORS["purple"],
            opacity=0.8,
        ))
        fig.add_vline(x=0.05, line_dash="dash", line_color=COLORS["green"],
                      annotation_text="p < 0.05")
        fig.update_layout(**PLOTLY_LAYOUT, title="Monte Carlo P-Value Distribution",
                          xaxis_title="P-Value", yaxis_title="Count")
        st.plotly_chart(fig, use_container_width=True)
    else:
        show_empty_state("No Monte Carlo p-values computed yet.")

# ---------------------------------------------------------------------------
# Win Rate vs Sharpe scatter
# ---------------------------------------------------------------------------
st.subheader("Win Rate vs Sharpe")

scatter_df = backtests.dropna(subset=["win_rate", "sharpe"])
if not scatter_df.empty:
    fig = go.Figure()
    for status in scatter_df["thesis_status"].unique():
        subset = scatter_df[scatter_df["thesis_status"] == status]
        fig.add_trace(go.Scatter(
            x=subset["win_rate"], y=subset["sharpe"],
            mode="markers",
            name=status.replace("_", " ").title(),
            marker=dict(
                color=STATUS_COLORS.get(status, COLORS["gray"]),
                size=subset["total_trades"].clip(lower=3, upper=30),
                opacity=0.7,
            ),
            text=subset["thesis_name"],
            hovertemplate="<b>%{text}</b><br>Win Rate: %{x:.1%}<br>Sharpe: %{y:.3f}<extra></extra>",
        ))
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="Win Rate vs Sharpe (size = trade count)",
        xaxis_title="Win Rate",
        yaxis_title="Sharpe Ratio",
        xaxis_tickformat=".0%",
    )
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Generator Leaderboard
# ---------------------------------------------------------------------------
st.subheader("Generator Leaderboard")

generator_data = theses.groupby(["generated_by", "status"]).size().reset_index(name="count")
generators = generator_data["generated_by"].unique()

if len(generators) > 0:
    fig = go.Figure()
    for status in status_order:
        subset = generator_data[generator_data["status"] == status]
        if not subset.empty:
            fig.add_trace(go.Bar(
                x=subset["generated_by"],
                y=subset["count"],
                name=status.replace("_", " ").title(),
                marker_color=STATUS_COLORS.get(status, COLORS["gray"]),
            ))
    fig.update_layout(**PLOTLY_LAYOUT, title="Theses by Generator", barmode="stack",
                      xaxis_title="Agent", yaxis_title="Count")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Kill Reasons
# ---------------------------------------------------------------------------
killed = theses[theses["status"] == "killed"]
if not killed.empty:
    reasons = killed["retirement_reason"].dropna()
    if not reasons.empty:
        st.subheader("Kill Reasons")
        reason_counts = reasons.value_counts().head(10)
        fig = go.Figure(go.Bar(
            y=reason_counts.index,
            x=reason_counts.values,
            orientation="h",
            marker_color=COLORS["red"],
        ))
        fig.update_layout(**PLOTLY_LAYOUT, title="Top Kill Reasons",
                          xaxis_title="Count", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Thesis Table
# ---------------------------------------------------------------------------
st.subheader("All Theses")

display = theses[["name", "status", "generated_by", "created_at"]].copy()
display["created_at"] = display["created_at"].apply(
    lambda x: x.strftime("%Y-%m-%d %H:%M") if x else "N/A"
)
display.columns = ["Name", "Status", "Generator", "Created"]

st.dataframe(display, use_container_width=True, hide_index=True)
