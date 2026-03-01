"""Model Registry — version history, metric trends, and quality gates.

Answers: "Are models improving over time?"
"""

import plotly.graph_objects as go
import streamlit as st

from components import (
    COLORS,
    PLOTLY_LAYOUT,
    humanize_bytes,
    humanize_duration,
    show_empty_state,
    time_ago,
)
from db import get_all_model_versions

st.title("Model Registry")

# ---------------------------------------------------------------------------
# Model type selector
# ---------------------------------------------------------------------------
model_type = st.selectbox(
    "Model Type",
    ["sentiment", "signal_ranker", "deep_hedging"],
    format_func=lambda x: {"sentiment": "FinBERT Sentiment", "signal_ranker": "XGBoost Signal Ranker", "deep_hedging": "Deep Hedging Policy"}[x],
)

df = get_all_model_versions(model_type)

if df.empty:
    show_empty_state(
        f"No {model_type} models trained yet. "
        "Models are trained weekly on Sundays via the ml_training Celery queue on your local GPU."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Version History Table
# ---------------------------------------------------------------------------
st.subheader("Version History")

display = df[["version", "is_active", "model_format", "model_size_bytes", "trained_at", "training_duration_seconds", "model_hash"]].copy()
display["model_size_bytes"] = display["model_size_bytes"].apply(humanize_bytes)
display["training_duration_seconds"] = display["training_duration_seconds"].apply(humanize_duration)
display["trained_at"] = display["trained_at"].apply(time_ago)
display["model_hash"] = display["model_hash"].apply(lambda x: x[:12] if x else "N/A")
display.columns = ["Version", "Active", "Format", "Size", "Trained", "Duration", "Hash"]

st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Active": st.column_config.CheckboxColumn(width="small"),
        "Version": st.column_config.NumberColumn(width="small"),
    },
)

# ---------------------------------------------------------------------------
# Extract JSONB metrics into columns
# ---------------------------------------------------------------------------
def safe_get(metrics, key):
    if isinstance(metrics, dict):
        return metrics.get(key)
    return None


versions = df.sort_values("version")

if model_type == "sentiment":
    versions["mse"] = versions["training_metrics"].apply(lambda x: safe_get(x, "mse"))
    versions["direction_agreement"] = versions["training_metrics"].apply(lambda x: safe_get(x, "direction_agreement"))
    versions["spearman"] = versions["training_metrics"].apply(lambda x: safe_get(x, "spearman_correlation"))

    st.subheader("Metric Trends")
    col1, col2 = st.columns(2)

    with col1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=versions["version"], y=versions["direction_agreement"],
            mode="lines+markers", name="Direction Agreement",
            line=dict(color=COLORS["green"], width=2),
            marker=dict(size=8),
        ))
        fig.add_hline(y=0.55, line_dash="dash", line_color=COLORS["yellow"],
                      annotation_text="Quality Gate (55%)")
        fig.update_layout(**PLOTLY_LAYOUT, title="Direction Agreement", yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=versions["version"], y=versions["mse"],
            mode="lines+markers", name="MSE",
            line=dict(color=COLORS["red"], width=2),
            marker=dict(size=8),
        ))
        fig.add_hline(y=0.25, line_dash="dash", line_color=COLORS["yellow"],
                      annotation_text="Quality Gate (0.25)")
        fig.update_layout(**PLOTLY_LAYOUT, title="MSE (lower is better)")
        st.plotly_chart(fig, use_container_width=True)

    # Spearman
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=versions["version"], y=versions["spearman"],
        mode="lines+markers", name="Spearman",
        line=dict(color=COLORS["blue"], width=2),
        marker=dict(size=8),
    ))
    fig.add_hline(y=0.10, line_dash="dash", line_color=COLORS["yellow"],
                  annotation_text="Quality Gate (0.10)")
    fig.update_layout(**PLOTLY_LAYOUT, title="Spearman Correlation")
    st.plotly_chart(fig, use_container_width=True)

elif model_type == "signal_ranker":
    versions["auc_roc"] = versions["training_metrics"].apply(lambda x: safe_get(x, "auc_roc"))
    versions["accuracy"] = versions["training_metrics"].apply(lambda x: safe_get(x, "accuracy"))

    st.subheader("Metric Trends")
    col1, col2 = st.columns(2)

    with col1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=versions["version"], y=versions["auc_roc"],
            mode="lines+markers", name="AUC-ROC",
            line=dict(color=COLORS["green"], width=2),
            marker=dict(size=8),
        ))
        fig.add_hline(y=0.6, line_dash="dash", line_color=COLORS["yellow"],
                      annotation_text="Quality Gate (0.6)")
        fig.update_layout(**PLOTLY_LAYOUT, title="AUC-ROC")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=versions["version"], y=versions["accuracy"],
            mode="lines+markers", name="Accuracy",
            line=dict(color=COLORS["blue"], width=2),
            marker=dict(size=8),
        ))
        fig.update_layout(**PLOTLY_LAYOUT, title="Accuracy")
        st.plotly_chart(fig, use_container_width=True)

elif model_type == "deep_hedging":
    versions["final_cvar"] = versions["training_metrics"].apply(lambda x: safe_get(x, "final_cvar"))
    versions["cvar_improvement"] = versions["training_metrics"].apply(lambda x: safe_get(x, "cvar_improvement_pct"))

    st.subheader("Metric Trends")
    col1, col2 = st.columns(2)

    with col1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=versions["version"], y=versions["final_cvar"],
            mode="lines+markers", name="Final CVaR",
            line=dict(color=COLORS["red"], width=2),
            marker=dict(size=8),
        ))
        fig.update_layout(**PLOTLY_LAYOUT, title="CVaR (tail risk, lower magnitude = better)")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=versions["version"], y=versions["cvar_improvement"],
            mode="lines+markers", name="CVaR Improvement",
            line=dict(color=COLORS["green"], width=2),
            marker=dict(size=8),
        ))
        fig.update_layout(**PLOTLY_LAYOUT, title="CVaR Improvement vs BSM (%)")
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Quality Gate Pass/Fail
# ---------------------------------------------------------------------------
if model_type == "sentiment":
    st.subheader("Quality Gate History")

    gate_data = []
    for _, row in versions.iterrows():
        tm = row.get("training_metrics")
        if isinstance(tm, dict) and "quality_gate_passed" in tm:
            gates = tm["quality_gate_passed"]
            gate_data.append({
                "version": row["version"],
                "direction_agreement": gates.get("direction_agreement", False),
                "spearman_correlation": gates.get("spearman_correlation", False),
                "mse": gates.get("mse", False),
                "sample_size": gates.get("sample_size", False),
            })

    if gate_data:
        import pandas as pd
        gate_df = pd.DataFrame(gate_data)
        gate_cols = ["direction_agreement", "spearman_correlation", "mse", "sample_size"]

        fig = go.Figure()
        for gc in gate_cols:
            fig.add_trace(go.Bar(
                x=gate_df["version"],
                y=[1 if v else -1 for v in gate_df[gc]],
                name=gc.replace("_", " ").title(),
                marker_color=[COLORS["green"] if v else COLORS["red"] for v in gate_df[gc]],
            ))
        fig.update_layout(
            **PLOTLY_LAYOUT,
            title="Quality Gate Pass/Fail by Version",
            barmode="group",
            yaxis=dict(tickvals=[-1, 1], ticktext=["Fail", "Pass"]),
        )
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Training Duration + Model Size Trends
# ---------------------------------------------------------------------------
st.subheader("Training Efficiency")

col1, col2 = st.columns(2)

with col1:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=versions["version"],
        y=versions["training_duration_seconds"],
        mode="lines+markers", name="Duration",
        line=dict(color=COLORS["orange"], width=2),
        marker=dict(size=8),
    ))
    fig.update_layout(**PLOTLY_LAYOUT, title="Training Duration (seconds)")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=versions["version"],
        y=versions["model_size_bytes"].apply(lambda x: x / 1024 if x else None),
        mode="lines+markers", name="Size",
        line=dict(color=COLORS["purple"], width=2),
        marker=dict(size=8),
    ))
    fig.update_layout(**PLOTLY_LAYOUT, title="Model Size (KB)")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Training Config (expandable)
# ---------------------------------------------------------------------------
with st.expander("Training Configuration (latest version)"):
    latest = df.iloc[0]
    config = latest.get("training_config")
    if config:
        st.json(config)
    else:
        st.caption("No training configuration recorded.")
