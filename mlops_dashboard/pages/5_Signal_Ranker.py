"""Signal Ranker — feature importances and AUC trends.

Answers: "What signals matter? What drives thesis quality?"
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import COLORS, PLOTLY_LAYOUT, humanize_duration, metric_row, show_empty_state
from db import get_signal_ranker_versions

st.title("Signal Ranker")

df = get_signal_ranker_versions()

if df.empty:
    show_empty_state(
        "No signal ranker models trained yet. Requires at least 50 backtested "
        "theses with generation_context to produce training data."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def safe_get(metrics, key):
    if isinstance(metrics, dict):
        return metrics.get(key)
    return None

# ---------------------------------------------------------------------------
# Active Model Summary
# ---------------------------------------------------------------------------
active = df[df["is_active"] == True]  # noqa: E712
if not active.empty:
    row = active.iloc[0]
    tm = row.get("training_metrics") or {}
    metric_row([
        {"label": "AUC-ROC", "value": f"{tm.get('auc_roc', 0):.3f}"},
        {"label": "Accuracy", "value": f"{tm.get('accuracy', 0):.1%}"},
        {"label": "Sample Size", "value": tm.get("sample_size", "N/A")},
        {"label": "Training Duration", "value": humanize_duration(row.get("training_duration_seconds"))},
    ])
    st.divider()

# ---------------------------------------------------------------------------
# Feature Importance Bar Chart
# ---------------------------------------------------------------------------
st.subheader("Feature Importances (Active Model)")

active_metrics = active.iloc[0].get("training_metrics") if not active.empty else None
if active_metrics and "feature_importances" in active_metrics:
    importances = active_metrics["feature_importances"]
    fi_df = pd.DataFrame([
        {"feature": k.replace("_", " ").title(), "importance": v}
        for k, v in importances.items()
    ]).sort_values("importance", ascending=True)

    fig = go.Figure(go.Bar(
        y=fi_df["feature"],
        x=fi_df["importance"],
        orientation="h",
        marker=dict(
            color=fi_df["importance"],
            colorscale=[[0, COLORS["blue"]], [1, COLORS["green"]]],
        ),
    ))
    fig.update_layout(**PLOTLY_LAYOUT, title="Feature Importances (Gain)",
                      xaxis_title="Importance", yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)
else:
    show_empty_state("No feature importances available for the active model.")

# ---------------------------------------------------------------------------
# Feature Importance Drift (heatmap across versions)
# ---------------------------------------------------------------------------
if len(df) > 1:
    st.subheader("Feature Importance Drift")

    all_features = set()
    version_importances = []
    for _, row in df.sort_values("version").iterrows():
        tm = row.get("training_metrics")
        if isinstance(tm, dict) and "feature_importances" in tm:
            fi = tm["feature_importances"]
            all_features.update(fi.keys())
            version_importances.append({"version": row["version"], **fi})

    if version_importances and len(all_features) > 0:
        drift_df = pd.DataFrame(version_importances).set_index("version")
        drift_df = drift_df.fillna(0)

        # Sort features by mean importance
        feature_order = drift_df.mean().sort_values(ascending=False).index.tolist()
        drift_df = drift_df[feature_order]

        fig = go.Figure(go.Heatmap(
            z=drift_df.values.T,
            x=[f"v{v}" for v in drift_df.index],
            y=[f.replace("_", " ").title() for f in drift_df.columns],
            colorscale="Viridis",
            hovertemplate="Version: %{x}<br>Feature: %{y}<br>Importance: %{z:.4f}<extra></extra>",
        ))
        fig.update_layout(**PLOTLY_LAYOUT, title="Feature Importance Across Versions",
                          xaxis_title="Version", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# AUC Trend
# ---------------------------------------------------------------------------
st.subheader("AUC-ROC Trend")

versions = df.sort_values("version")
versions["auc_roc"] = versions["training_metrics"].apply(lambda x: safe_get(x, "auc_roc"))

auc_data = versions.dropna(subset=["auc_roc"])
if not auc_data.empty:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=auc_data["version"], y=auc_data["auc_roc"],
        mode="lines+markers",
        line=dict(color=COLORS["green"], width=2),
        marker=dict(size=8),
    ))
    fig.add_hline(y=0.6, line_dash="dash", line_color=COLORS["yellow"],
                  annotation_text="Quality Gate (0.6)")
    fig.add_hline(y=0.5, line_dash="dash", line_color=COLORS["red"],
                  annotation_text="Random (0.5)")
    fig.update_layout(**PLOTLY_LAYOUT, title="AUC-ROC Across Versions")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Class Balance
# ---------------------------------------------------------------------------
st.subheader("Class Balance")

balance_data = []
for _, row in versions.iterrows():
    tm = row.get("training_metrics")
    if isinstance(tm, dict):
        balance_data.append({
            "version": row["version"],
            "train_positive_rate": tm.get("positive_rate_train"),
            "test_positive_rate": tm.get("positive_rate_test"),
        })

if balance_data:
    balance_df = pd.DataFrame(balance_data).dropna()
    if not balance_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=balance_df["version"], y=balance_df["train_positive_rate"],
            name="Train Positive Rate", marker_color=COLORS["blue"],
        ))
        fig.add_trace(go.Bar(
            x=balance_df["version"], y=balance_df["test_positive_rate"],
            name="Test Positive Rate", marker_color=COLORS["green"],
        ))
        fig.update_layout(**PLOTLY_LAYOUT, title="Class Balance (Positive Rate per Split)",
                          barmode="group", xaxis_title="Version",
                          yaxis_title="Positive Rate", yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Version Config Comparison
# ---------------------------------------------------------------------------
with st.expander("Training Configuration Comparison"):
    config_data = []
    for _, row in df.sort_values("version", ascending=False).iterrows():
        tc = row.get("training_config")
        if isinstance(tc, dict):
            config_data.append({"version": f"v{row['version']}", **tc})
    if config_data:
        st.dataframe(pd.DataFrame(config_data), use_container_width=True, hide_index=True)
    else:
        st.caption("No training configurations recorded.")
