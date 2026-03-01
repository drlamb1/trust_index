"""Database query layer for the MLOps dashboard.

Read-only connection to Neon PostgreSQL. All queries return pandas DataFrames.
Cached with 5-minute TTL via Streamlit's @st.cache_data.

Credentials are resolved in order:
  1. st.secrets["neon"] (Streamlit Cloud / .streamlit/secrets.toml)
  2. Environment variables via .env (local dev)
"""

import os

import pandas as pd
import psycopg2
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def _get_secret(key: str, default: str | None = None) -> str:
    """Resolve a credential from st.secrets first, then env vars."""
    try:
        return st.secrets["neon"][key]
    except (KeyError, FileNotFoundError):
        val = os.environ.get(key, default)
        if val is None:
            raise KeyError(
                f"Missing credential '{key}'. Set it in .streamlit/secrets.toml "
                f"under [neon] or as an environment variable."
            )
        return val


@st.cache_resource
def get_connection():
    """Return a psycopg2 connection to Neon PostgreSQL."""
    return psycopg2.connect(
        host=_get_secret("NEON_HOST", "ep-long-moon-aiq00ucz-pooler.c-4.us-east-1.aws.neon.tech"),
        port=int(_get_secret("NEON_PORT", "5432")),
        user=_get_secret("NEON_USER", "neondb_owner"),
        password=_get_secret("NEON_PASSWORD"),
        dbname=_get_secret("NEON_DB", "neondb"),
        sslmode="require",
    )


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Execute SQL and return a pandas DataFrame. Handles reconnection on failure."""
    conn = get_connection()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    except (psycopg2.OperationalError, psycopg2.InterfaceError, pd.errors.DatabaseError):
        # Neon cold-starts or pooler timeouts surface as DatabaseError via pandas
        st.cache_resource.clear()
        conn = get_connection()
        return pd.read_sql_query(sql, conn, params=params)


# ---------------------------------------------------------------------------
# System Pulse queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def get_active_models() -> pd.DataFrame:
    return query_df("""
        SELECT model_type, version, is_active, model_format,
               model_size_bytes, model_hash, trained_at,
               training_duration_seconds, training_metrics, eval_metrics,
               training_config, training_data_stats
        FROM ml_models
        WHERE is_active = true
        ORDER BY model_type
    """)


@st.cache_data(ttl=300)
def get_thesis_status_counts() -> pd.DataFrame:
    return query_df("""
        SELECT status, COUNT(*) as count
        FROM simulated_theses
        GROUP BY status
        ORDER BY count DESC
    """)


@st.cache_data(ttl=300)
def get_recent_simulation_logs(hours: int = 24) -> pd.DataFrame:
    return query_df(
        """
        SELECT id, agent_name, event_type, event_data, thesis_id, created_at
        FROM simulation_logs
        WHERE created_at >= NOW() - make_interval(hours := %s)
        ORDER BY created_at DESC
        LIMIT 200
        """,
        (hours,),
    )


@st.cache_data(ttl=300)
def get_backtest_summary() -> pd.DataFrame:
    return query_df("""
        SELECT COUNT(*) as total_backtests,
               AVG(sharpe) as avg_sharpe,
               AVG(win_rate) as avg_win_rate,
               AVG(max_drawdown) as avg_max_drawdown
        FROM backtest_runs
        WHERE sharpe IS NOT NULL
    """)


@st.cache_data(ttl=300)
def get_training_readiness() -> dict:
    """Check data prerequisites for each model's training task."""
    # Sentiment: needs >= 2000 news articles with sentiment_score AND price_move_1d
    sentiment_df = query_df("""
        SELECT COUNT(*) as count FROM news_articles
        WHERE sentiment_score IS NOT NULL AND price_move_1d IS NOT NULL
        AND char_length(title) >= 10
    """)
    sentiment_samples = int(sentiment_df.iloc[0]["count"]) if not sentiment_df.empty else 0

    # Signal ranker: needs >= 50 backtested theses with generation_context
    ranker_df = query_df("""
        SELECT COUNT(DISTINCT st.id) as count
        FROM simulated_theses st
        JOIN backtest_runs br ON st.id = br.thesis_id
        WHERE st.generation_context IS NOT NULL
        AND st.status IN ('paper_live', 'killed')
    """)
    ranker_samples = int(ranker_df.iloc[0]["count"]) if not ranker_df.empty else 0

    # Deep hedging: needs >= 1 heston calibration
    heston_df = query_df("SELECT COUNT(*) as count FROM heston_calibrations")
    heston_count = int(heston_df.iloc[0]["count"]) if not heston_df.empty else 0

    return {
        "sentiment": {"current": sentiment_samples, "required": 2000},
        "signal_ranker": {"current": ranker_samples, "required": 50},
        "deep_hedging": {"current": heston_count, "required": 1},
    }


# ---------------------------------------------------------------------------
# Model Registry queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def get_all_model_versions(model_type: str | None = None) -> pd.DataFrame:
    if model_type:
        return query_df(
            """
            SELECT id, model_type, version, is_active, model_format,
                   model_size_bytes, model_hash, trained_at,
                   training_duration_seconds, training_metrics,
                   eval_metrics, training_config, training_data_stats
            FROM ml_models
            WHERE model_type = %s
            ORDER BY version DESC
            """,
            (model_type,),
        )
    return query_df("""
        SELECT id, model_type, version, is_active, model_format,
               model_size_bytes, model_hash, trained_at,
               training_duration_seconds, training_metrics,
               eval_metrics, training_config, training_data_stats
        FROM ml_models
        ORDER BY model_type, version DESC
    """)


# ---------------------------------------------------------------------------
# Thesis Lifecycle queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def get_thesis_lifecycle_data() -> pd.DataFrame:
    return query_df("""
        SELECT id, name, status, generated_by, generation_context,
               ticker_ids, created_at, retired_at, retirement_reason,
               parent_thesis_id
        FROM simulated_theses
        ORDER BY created_at DESC
    """)


@st.cache_data(ttl=300)
def get_backtest_results() -> pd.DataFrame:
    return query_df("""
        SELECT br.id, br.thesis_id, br.sharpe, br.sortino,
               br.max_drawdown, br.win_rate, br.profit_factor,
               br.expectancy, br.total_trades, br.monte_carlo_p_value,
               br.ran_at, br.start_date, br.end_date,
               st.name as thesis_name, st.generated_by, st.status as thesis_status,
               t.symbol as ticker_symbol
        FROM backtest_runs br
        JOIN simulated_theses st ON br.thesis_id = st.id
        JOIN tickers t ON br.ticker_id = t.id
        WHERE br.sharpe IS NOT NULL
        ORDER BY br.ran_at DESC
    """)


# ---------------------------------------------------------------------------
# Sentiment queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def get_sentiment_data() -> pd.DataFrame:
    return query_df("""
        SELECT sentiment_score, price_move_1d, price_move_5d,
               sentiment_model, sentiment_scored_at, published_at
        FROM news_articles
        WHERE sentiment_score IS NOT NULL
        ORDER BY published_at DESC
        LIMIT 5000
    """)


@st.cache_data(ttl=300)
def get_article_volume_over_time() -> pd.DataFrame:
    return query_df("""
        SELECT DATE(published_at) as date, COUNT(*) as count,
               AVG(sentiment_score) as avg_sentiment
        FROM news_articles
        WHERE published_at IS NOT NULL
        GROUP BY DATE(published_at)
        ORDER BY date
    """)


# ---------------------------------------------------------------------------
# Signal Ranker queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def get_signal_ranker_versions() -> pd.DataFrame:
    return query_df("""
        SELECT version, is_active, trained_at, training_duration_seconds,
               training_metrics, eval_metrics, training_config,
               training_data_stats, model_size_bytes
        FROM ml_models
        WHERE model_type = 'signal_ranker'
        ORDER BY version DESC
    """)


# ---------------------------------------------------------------------------
# Agent Activity queries
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def get_agent_activity(days: int = 7) -> pd.DataFrame:
    return query_df(
        """
        SELECT agent_name, event_type, event_data, thesis_id, created_at
        FROM simulation_logs
        WHERE created_at >= NOW() - make_interval(days := %s)
        ORDER BY created_at DESC
        """,
        (days,),
    )


@st.cache_data(ttl=300)
def get_agent_memory_status() -> pd.DataFrame:
    return query_df("""
        SELECT agent_name, memory_type, COUNT(*) as count,
               AVG(confidence) as avg_confidence,
               MAX(last_accessed) as last_accessed
        FROM agent_memories
        GROUP BY agent_name, memory_type
        ORDER BY agent_name
    """)
