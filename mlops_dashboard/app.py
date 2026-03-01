"""EdgeFinder MLOps Observability Dashboard.

Standalone Streamlit app for monitoring the ML pipeline, thesis lifecycle,
and agent ecosystem. Read-only connection to Neon PostgreSQL.
"""

import streamlit as st

# ---------------------------------------------------------------------------
# Navigation (st.navigation + st.Page — Streamlit 1.36+)
# ---------------------------------------------------------------------------
pages = st.navigation([
    st.Page("pages/1_System_Pulse.py",    title="System Pulse",     icon=":material/monitor_heart:"),
    st.Page("pages/2_Model_Registry.py",  title="Model Registry",   icon=":material/inventory:"),
    st.Page("pages/3_Thesis_Lifecycle.py", title="Thesis Lifecycle", icon=":material/timeline:"),
    st.Page("pages/4_Sentiment.py",       title="Sentiment",        icon=":material/sentiment_satisfied:"),
    st.Page("pages/5_Signal_Ranker.py",   title="Signal Ranker",    icon=":material/leaderboard:"),
    st.Page("pages/6_Agent_Activity.py",  title="Agent Activity",   icon=":material/smart_toy:"),
])

st.set_page_config(
    page_title="EdgeFinder MLOps",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    [data-testid="stMetricValue"] {
        font-size: 28px;
        font-weight: 700;
    }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 1rem;
    }
    [data-testid="stSidebar"] {
        background-color: #0E1117;
    }
    h1 {
        color: #00C851;
        border-bottom: 2px solid #1A1D23;
        padding-bottom: 0.5rem;
    }
    h2 {
        color: #CCCCCC;
    }
    .stDataFrame {
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.title("EdgeFinder MLOps")
st.sidebar.caption("Read-only observability dashboard")
st.sidebar.divider()

auto_refresh = st.sidebar.checkbox("Auto-refresh (5 min)", value=False)

if st.sidebar.button("Refresh Now"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.caption("All data is read-only from production Neon DB.")
st.sidebar.caption("All P&L values are simulated play money.")

# ---------------------------------------------------------------------------
# Run the selected page
# ---------------------------------------------------------------------------
pages.run()

# ---------------------------------------------------------------------------
# Auto-refresh loop
# ---------------------------------------------------------------------------
if auto_refresh:
    import time
    time.sleep(300)
    st.rerun()
