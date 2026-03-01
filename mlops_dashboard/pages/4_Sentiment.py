"""Sentiment Analysis — NLP model effectiveness.

Answers: "Does our sentiment model actually predict price moves?"
"""

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from components import COLORS, PLOTLY_LAYOUT, metric_row, show_empty_state
from db import get_active_models, get_article_volume_over_time, get_sentiment_data

st.title("Sentiment Analysis")

sentiment_df = get_sentiment_data()

if sentiment_df.empty:
    show_empty_state(
        "No sentiment-scored articles found. Articles are scored during ingestion "
        "via the FinBERT model or Haiku API fallback."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Summary Metrics
# ---------------------------------------------------------------------------
total_scored = len(sentiment_df)
avg_sentiment = sentiment_df["sentiment_score"].mean()

# Direction agreement: sign(sentiment) matches sign(price_move_1d)
paired = sentiment_df.dropna(subset=["sentiment_score", "price_move_1d"])
if not paired.empty:
    correct = ((paired["sentiment_score"] > 0) == (paired["price_move_1d"] > 0)).mean()
    direction_agreement = f"{correct:.1%}"
else:
    direction_agreement = "N/A"

models = get_active_models()
sentiment_model = models[models["model_type"] == "sentiment"]
model_version = f"v{sentiment_model.iloc[0]['version']}" if not sentiment_model.empty else "None"

metric_row([
    {"label": "Articles Scored", "value": f"{total_scored:,}"},
    {"label": "Avg Sentiment", "value": f"{avg_sentiment:.3f}"},
    {"label": "Direction Agreement", "value": direction_agreement},
    {"label": "Active Model", "value": model_version},
])

# ---------------------------------------------------------------------------
# Sentiment Score Distribution
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Score Distribution")

fig = go.Figure()
fig.add_trace(go.Histogram(
    x=sentiment_df["sentiment_score"],
    nbinsx=50,
    marker=dict(
        color=sentiment_df["sentiment_score"],
        colorscale=[[0, COLORS["red"]], [0.5, COLORS["gray"]], [1, COLORS["green"]]],
    ),
    opacity=0.8,
))
fig.add_vline(x=0, line_dash="dash", line_color="white", annotation_text="Neutral")
fig.update_layout(**PLOTLY_LAYOUT, title="Sentiment Score Distribution (-1 to +1)",
                  xaxis_title="Sentiment Score", yaxis_title="Count")
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Sentiment vs Price Move Scatters
# ---------------------------------------------------------------------------
if not paired.empty:
    st.subheader("Predictive Power")
    col1, col2 = st.columns(2)

    with col1:
        # 1-day
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=paired["sentiment_score"],
            y=paired["price_move_1d"],
            mode="markers",
            marker=dict(color=COLORS["blue"], opacity=0.3, size=4),
            name="Articles",
        ))

        # OLS trend line
        mask = paired["sentiment_score"].notna() & paired["price_move_1d"].notna()
        x = paired.loc[mask, "sentiment_score"].values
        y = paired.loc[mask, "price_move_1d"].values
        if len(x) > 2:
            coeffs = np.polyfit(x, y, 1)
            x_line = np.linspace(x.min(), x.max(), 100)
            y_line = np.polyval(coeffs, x_line)
            fig.add_trace(go.Scatter(
                x=x_line, y=y_line,
                mode="lines", name=f"Trend (slope={coeffs[0]:.4f})",
                line=dict(color=COLORS["green"], width=2),
            ))

        fig.update_layout(**PLOTLY_LAYOUT, title="Sentiment vs 1-Day Price Move",
                          xaxis_title="Sentiment Score", yaxis_title="1-Day Return",
                          yaxis_tickformat=".1%")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # 5-day
        paired_5d = sentiment_df.dropna(subset=["sentiment_score", "price_move_5d"])
        if not paired_5d.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=paired_5d["sentiment_score"],
                y=paired_5d["price_move_5d"],
                mode="markers",
                marker=dict(color=COLORS["purple"], opacity=0.3, size=4),
                name="Articles",
            ))

            x5 = paired_5d["sentiment_score"].values
            y5 = paired_5d["price_move_5d"].values
            if len(x5) > 2:
                coeffs5 = np.polyfit(x5, y5, 1)
                x_line5 = np.linspace(x5.min(), x5.max(), 100)
                y_line5 = np.polyval(coeffs5, x_line5)
                fig.add_trace(go.Scatter(
                    x=x_line5, y=y_line5,
                    mode="lines", name=f"Trend (slope={coeffs5[0]:.4f})",
                    line=dict(color=COLORS["green"], width=2),
                ))

            fig.update_layout(**PLOTLY_LAYOUT, title="Sentiment vs 5-Day Price Move",
                              xaxis_title="Sentiment Score", yaxis_title="5-Day Return",
                              yaxis_tickformat=".1%")
            st.plotly_chart(fig, use_container_width=True)
        else:
            show_empty_state("No 5-day price move data linked yet.")

# ---------------------------------------------------------------------------
# Rolling Direction Accuracy
# ---------------------------------------------------------------------------
if not paired.empty and len(paired) >= 50:
    st.subheader("Rolling Direction Accuracy")

    sorted_paired = paired.sort_values("published_at")
    sorted_paired["correct"] = (
        (sorted_paired["sentiment_score"] > 0) == (sorted_paired["price_move_1d"] > 0)
    ).astype(float)
    sorted_paired["rolling_accuracy"] = sorted_paired["correct"].rolling(100, min_periods=50).mean()

    valid_rolling = sorted_paired.dropna(subset=["rolling_accuracy"])
    if not valid_rolling.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=valid_rolling["published_at"],
            y=valid_rolling["rolling_accuracy"],
            mode="lines",
            line=dict(color=COLORS["green"], width=2),
            name="100-article rolling accuracy",
        ))
        fig.add_hline(y=0.50, line_dash="dash", line_color=COLORS["red"],
                      annotation_text="Coin flip (50%)")
        fig.add_hline(y=0.55, line_dash="dash", line_color=COLORS["yellow"],
                      annotation_text="Quality gate (55%)")
        fig.update_layout(**PLOTLY_LAYOUT, title="Rolling Direction Accuracy (100-article window)",
                          xaxis_title="Date", yaxis_title="Accuracy",
                          yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Article Volume Over Time
# ---------------------------------------------------------------------------
st.subheader("Article Volume")

volume_df = get_article_volume_over_time()
if not volume_df.empty:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=volume_df["date"], y=volume_df["count"],
        name="Articles",
        marker_color=COLORS["blue"],
        opacity=0.6,
    ))
    fig.add_trace(go.Scatter(
        x=volume_df["date"], y=volume_df["avg_sentiment"],
        name="Avg Sentiment",
        mode="lines",
        line=dict(color=COLORS["green"], width=2),
        yaxis="y2",
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="Daily Article Volume & Average Sentiment",
        xaxis_title="Date",
        yaxis_title="Article Count",
        yaxis2=dict(
            title="Avg Sentiment",
            overlaying="y",
            side="right",
            range=[-1, 1],
            showgrid=False,
        ),
    )
    st.plotly_chart(fig, use_container_width=True)
