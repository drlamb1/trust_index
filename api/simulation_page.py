"""
EdgeFinder — Simulation Dashboard HTML Page

Learning-first design. Every metric has context. Every number teaches.
All P&L is simulated play-money.
"""


def simulation_page_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EdgeFinder — Simulation Lab</title>
<style>
:root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --gold: #d29922;
    --purple: #9b59b6; --blue: #00d4ff; --orange: #ff6b35;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'SF Mono', 'Cascadia Code', monospace; background: var(--bg); color: var(--text); }
a { color: var(--accent); text-decoration: none; }

.disclaimer {
    background: #1c1208; border: 1px solid var(--gold); color: var(--gold);
    padding: 8px 16px; text-align: center; font-size: 12px;
}
.header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 16px 24px; border-bottom: 1px solid var(--border);
}
.header h1 { font-size: 20px; color: var(--text); }
.header .portfolio-value { font-size: 18px; color: var(--green); }

.layout {
    display: grid; grid-template-columns: 280px 1fr; height: calc(100vh - 90px);
}
.sidebar {
    border-right: 1px solid var(--border); overflow-y: auto; padding: 12px;
}
.sidebar h3 { font-size: 13px; color: var(--muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }
.feed-item {
    background: var(--card); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 10px; margin-bottom: 6px; font-size: 11px; cursor: pointer;
    transition: border-color 0.2s;
}
.feed-item:hover { border-color: var(--accent); }
.feed-item .agent { font-weight: 600; margin-right: 4px; }
.feed-item .time { color: var(--muted); font-size: 10px; float: right; }

.main { overflow-y: auto; padding: 16px 24px; }
.section { margin-bottom: 24px; }
.section h2 { font-size: 15px; color: var(--accent); margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }

.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.card {
    background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: 14px; transition: border-color 0.2s;
}
.card:hover { border-color: var(--accent); }
.card h4 { font-size: 14px; margin-bottom: 6px; }
.card .status { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 10px; font-weight: 600; }
.status-proposed { background: #1f2d3d; color: var(--accent); }
.status-backtesting { background: #2d1f1f; color: var(--orange); }
.status-paper_live { background: #1f2d1f; color: var(--green); }
.status-retired, .status-killed { background: #2d1f1f; color: var(--red); }
.card .metrics { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; margin-top: 8px; }
.metric { text-align: center; }
.metric .label { font-size: 10px; color: var(--muted); }
.metric .value { font-size: 14px; font-weight: 600; }
.val-up { color: var(--green); }
.val-dn { color: var(--red); }

table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; color: var(--muted); font-size: 11px; padding: 6px 8px; border-bottom: 1px solid var(--border); }
td { padding: 6px 8px; border-bottom: 1px solid var(--border); }

.heston-params { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
.param-box { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 8px; text-align: center; }
.param-box .name { font-size: 10px; color: var(--muted); }
.param-box .val { font-size: 16px; font-weight: 600; color: var(--blue); }

.memory-card {
    background: var(--card); border-left: 3px solid var(--purple);
    padding: 10px 14px; margin-bottom: 8px; border-radius: 0 6px 6px 0;
}
.memory-card .type { font-size: 10px; color: var(--purple); text-transform: uppercase; }
.memory-card .content { font-size: 12px; margin-top: 4px; }
.memory-card .confidence { font-size: 10px; color: var(--muted); margin-top: 4px; }

.stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.stat-card { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 12px; text-align: center; }
.stat-card .num { font-size: 22px; font-weight: 700; color: var(--accent); }
.stat-card .desc { font-size: 10px; color: var(--muted); margin-top: 4px; }

.tooltip { position: relative; cursor: help; color: var(--muted); }
.tooltip:hover::after {
    content: attr(data-tip); position: absolute; left: 0; top: 100%;
    background: #1c2128; border: 1px solid var(--border); padding: 6px 10px;
    font-size: 11px; width: 220px; z-index: 10; border-radius: 4px;
    color: var(--text);
}
.loading { color: var(--muted); font-style: italic; font-size: 12px; }
.nav-links { display: flex; gap: 16px; font-size: 13px; }
</style>
</head>
<body>
<div class="disclaimer">All P&L is simulated play-money. This is a learning lab, not financial advice.</div>
<div class="header">
    <div>
        <h1>Simulation Lab</h1>
        <div class="nav-links"><a href="/briefing">Briefing</a> <a href="/simulation">Simulation</a></div>
    </div>
    <div class="portfolio-value" id="portfolio-value">Loading...</div>
</div>
<div class="layout">
    <div class="sidebar">
        <h3>Agent Feed</h3>
        <div id="agent-feed"><div class="loading">Connecting...</div></div>
    </div>
    <div class="main">
        <div class="section">
            <h2>Overview</h2>
            <div class="stats-grid" id="stats-grid"><div class="loading">Loading stats...</div></div>
        </div>
        <div class="section">
            <h2>Active Theses</h2>
            <div class="cards" id="theses-cards"><div class="loading">Loading theses...</div></div>
        </div>
        <div class="section">
            <h2>Paper Portfolio <span class="tooltip" data-tip="Simulated positions linked to auto-generated theses. All play-money.">(?)</span></h2>
            <div id="portfolio-table"><div class="loading">Loading positions...</div></div>
        </div>
        <div class="section">
            <h2>Learning Journal</h2>
            <div id="memories-list"><div class="loading">Loading memories...</div></div>
        </div>
    </div>
</div>
<script>
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

const AGENT_COLORS = {
    thesis_lord: '#d29922', vol_slayer: '#00d4ff', heston_cal: '#ff6b35',
    deep_hedge: '#39ff14', post_mortem: '#9b59b6', paper_portfolio: '#3fb950',
    lifecycle_review: '#8b949e',
};

function fmt(n, d=2) { return n != null ? Number(n).toFixed(d) : '—'; }
function pct(n) { return n != null ? (n >= 0 ? '+' : '') + (n*100).toFixed(1) + '%' : '—'; }
function pnlClass(n) { return n > 0 ? 'val-up' : n < 0 ? 'val-dn' : ''; }
function ago(iso) {
    if (!iso) return '';
    const d = (Date.now() - new Date(iso)) / 60000;
    if (d < 60) return Math.floor(d) + 'm ago';
    if (d < 1440) return Math.floor(d/60) + 'h ago';
    return Math.floor(d/1440) + 'd ago';
}

async function loadStats() {
    try {
        const r = await fetch('/api/simulation/stats');
        const d = await r.json();
        $('#stats-grid').innerHTML = `
            <div class="stat-card"><div class="num">${d.theses?.total || 0}</div><div class="desc">Total Theses</div></div>
            <div class="stat-card"><div class="num">${d.backtests || 0}</div><div class="desc">Backtests Run</div></div>
            <div class="stat-card"><div class="num ${pnlClass(d.portfolio?.pnl)}">$${fmt(d.portfolio?.value,0)}</div><div class="desc">Portfolio (Play $)</div></div>
            <div class="stat-card"><div class="num ${pnlClass(d.portfolio?.pnl)}">${pct(d.portfolio?.pnl_pct)}</div><div class="desc">Total P&L</div></div>
            <div class="stat-card"><div class="num">${d.memories || 0}</div><div class="desc">Agent Memories</div></div>
            <div class="stat-card"><div class="num">${d.log_entries || 0}</div><div class="desc">Decision Log</div></div>
        `;
        $('#portfolio-value').textContent = `Play Money: $${fmt(d.portfolio?.value, 0)}`;
        $('#portfolio-value').className = 'portfolio-value ' + pnlClass(d.portfolio?.pnl);
    } catch(e) { $('#stats-grid').innerHTML = '<div class="loading">Stats unavailable</div>'; }
}

async function loadTheses() {
    try {
        const r = await fetch('/api/simulation/theses?limit=10');
        const theses = await r.json();
        if (!theses.length) { $('#theses-cards').innerHTML = '<div class="loading">No theses generated yet. The Thesis Lord generates them every 6 hours from converging signals.</div>'; return; }
        $('#theses-cards').innerHTML = theses.map(t => `
            <div class="card">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <h4>${t.name}</h4>
                    <span class="status status-${t.status}">${t.status.replace('_',' ')}</span>
                </div>
                <div style="font-size:11px;color:var(--muted);margin:4px 0">${t.thesis_text || ''}</div>
                <div style="font-size:10px;color:var(--muted)">${ago(t.created_at)} &middot; by ${t.generated_by}</div>
            </div>
        `).join('');
    } catch(e) { $('#theses-cards').innerHTML = '<div class="loading">Could not load theses</div>'; }
}

async function loadPortfolio() {
    try {
        const r = await fetch('/api/simulation/portfolio');
        const d = await r.json();
        if (!d.positions?.length) {
            $('#portfolio-table').innerHTML = '<div class="loading">No open positions. Theses that pass backtesting enter the paper portfolio automatically.</div>';
            return;
        }
        let html = '<table><tr><th>Ticker</th><th>Thesis</th><th>Side</th><th>Shares</th><th>Entry</th><th>Current</th><th>P&L</th><th>Stop/TP</th></tr>';
        for (const p of d.positions) {
            html += `<tr>
                <td><strong>${p.ticker}</strong></td>
                <td style="font-size:11px">${p.thesis}</td>
                <td>${p.side}</td>
                <td>${p.shares}</td>
                <td>$${fmt(p.entry_price)}</td>
                <td>$${fmt(p.current_price)}</td>
                <td class="${pnlClass(p.unrealized_pnl)}">${pct(p.unrealized_pnl_pct)}</td>
                <td style="font-size:10px">$${fmt(p.stop_loss,0)} / $${fmt(p.take_profit,0)}</td>
            </tr>`;
        }
        html += '</table>';
        html += `<div style="margin-top:8px;font-size:11px;color:var(--muted)">Cash: $${fmt(d.cash,0)} &middot; Total Value: $${fmt(d.total_value,0)} &middot; P&L: <span class="${pnlClass(d.total_pnl)}">${pct(d.total_pnl_pct)}</span></div>`;
        $('#portfolio-table').innerHTML = html;
    } catch(e) { $('#portfolio-table').innerHTML = '<div class="loading">Could not load portfolio</div>'; }
}

async function loadMemories() {
    try {
        const r = await fetch('/api/simulation/memories?limit=10');
        const mems = await r.json();
        if (!mems.length) { $('#memories-list').innerHTML = '<div class="loading">No agent memories yet. The Post-Mortem Priest consolidates lessons weekly.</div>'; return; }
        const icons = {insight:'\\u{1F4A1}', pattern:'\\u{1F504}', failure:'\\u26A0\\uFE0F', success:'\\u2705'};
        $('#memories-list').innerHTML = mems.map(m => `
            <div class="memory-card">
                <div class="type">${icons[m.memory_type]||''} ${m.memory_type}</div>
                <div class="content">${m.content}</div>
                <div class="confidence">Confidence: ${(m.confidence*100).toFixed(0)}% &middot; Agent: ${m.agent_name} &middot; Accessed ${m.access_count}x</div>
            </div>
        `).join('');
    } catch(e) { $('#memories-list').innerHTML = '<div class="loading">Could not load memories</div>'; }
}

function connectFeed() {
    const feed = $('#agent-feed');
    try {
        const es = new EventSource('/simulation/stream');
        es.onmessage = (e) => {
            const d = JSON.parse(e.data);
            if (d.type === 'connected') { feed.innerHTML = ''; return; }
            const color = AGENT_COLORS[d.agent] || '#8b949e';
            const item = document.createElement('div');
            item.className = 'feed-item';
            item.innerHTML = `<span class="agent" style="color:${color}">${d.agent}</span> ${d.event_type} <span class="time">${ago(d.created_at)}</span>`;
            feed.prepend(item);
            if (feed.children.length > 50) feed.lastChild.remove();
        };
        es.onerror = () => { feed.innerHTML = '<div class="loading">Feed disconnected. Refresh to reconnect.</div>'; };
    } catch(e) {
        feed.innerHTML = '<div class="loading">Agent feed unavailable</div>';
    }
}

// Initialize
loadStats();
loadTheses();
loadPortfolio();
loadMemories();
connectFeed();
setInterval(loadStats, 60000);
</script>
</body>
</html>"""
