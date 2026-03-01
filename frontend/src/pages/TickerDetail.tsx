// Ticker Detail — signal → thesis → backtest trace view
// Header | Price Chart | Technicals | Theses | Backtests | Alerts

import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip,
} from 'recharts'
import { ArrowLeft, TrendingUp, TrendingDown, Minus, AlertTriangle, BarChart2 } from 'lucide-react'
import { ticker as tickerApi } from '@/lib/api'
import type { SimulatedThesis } from '@/types/api'

// ─── Helpers ───

const STATUS_COLOR: Record<string, string> = {
  proposed:   'var(--color-text-muted)',
  backtesting:'var(--color-amber)',
  paper_live: 'var(--color-success)',
  retired:    'var(--color-text-dim)',
  killed:     'var(--color-danger)',
}

const SEVERITY_COLOR: Record<string, string> = {
  green:  'var(--color-success)',
  yellow: 'var(--color-amber)',
  red:    'var(--color-danger)',
}

const ALERT_TYPE_LABEL: Record<string, string> = {
  buy_the_dip:   'Buy the Dip',
  filing_risk:   'Filing Risk',
  volume_spike:  'Volume Spike',
  insider_buy:   'Insider Buy',
  earnings_beat: 'Earnings Beat',
  earnings_miss: 'Earnings Miss',
}

function fmt(n: number | null | undefined, decimals = 2, suffix = '') {
  if (n == null) return '—'
  return `${n.toFixed(decimals)}${suffix}`
}

function pctColor(v: number | null) {
  if (v == null) return 'var(--color-text-muted)'
  return v >= 0 ? 'var(--color-amber)' : 'var(--color-danger)'
}

// ─── Sub-components ───

function StatChip({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div
      className="glass-sm text-center"
      style={{ padding: '10px 16px', minWidth: 100 }}
    >
      <div style={{ fontFamily: 'var(--font-sans)', fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 500, color: color ?? 'var(--color-text-primary)' }}>
        {value}
      </div>
    </div>
  )
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h3 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 12 }}>
      {children}
    </h3>
  )
}

function ThesisRow({ thesis }: { thesis: SimulatedThesis }) {
  const color = STATUS_COLOR[thesis.status] ?? 'var(--color-text-muted)'
  const navigate = useNavigate()
  return (
    <div
      onClick={() => navigate(`/chat?persona=thesis_lord&message=${encodeURIComponent(`What's the status of thesis "${thesis.name}" (ID ${thesis.id})? Full picture.`)}`)}
      style={{ padding: '10px 0', borderBottom: '1px solid var(--color-border)', display: 'flex', alignItems: 'flex-start', gap: 12, cursor: 'pointer' }}
    >
      <BarChart2 size={13} style={{ color, flexShrink: 0, marginTop: 2 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--color-amber)', marginBottom: 2 }}>
          {thesis.name}
        </div>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
          {thesis.thesis_text}
        </div>
      </div>
      <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
        <span className="pill" style={{ background: color + '20', color, border: `1px solid ${color}40`, fontSize: 9 }}>
          {thesis.status.replace('_', ' ')}
        </span>
        {thesis.time_horizon_days && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--color-text-dim)' }}>
            {thesis.time_horizon_days}d horizon
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Main Page ───

export default function TickerDetail() {
  const { symbol = '' } = useParams<{ symbol: string }>()
  const sym = symbol.toUpperCase()

  const { data: summary, isLoading, isError } = useQuery({
    queryKey: ['ticker-summary', sym],
    queryFn: () => tickerApi.summary(sym),
    enabled: !!sym,
  })

  const { data: priceHistory = [] } = useQuery({
    queryKey: ['ticker-price-history', sym],
    queryFn: () => tickerApi.priceHistory(sym, 90),
    enabled: !!sym,
  })

  const { data: alerts = [] } = useQuery({
    queryKey: ['ticker-alerts', sym],
    queryFn: () => tickerApi.alerts(sym),
    enabled: !!sym,
  })

  const { data: theses = [] } = useQuery({
    queryKey: ['ticker-theses', sym],
    queryFn: () => tickerApi.theses(sym),
    enabled: !!sym,
  })

  const { data: backtests = [] } = useQuery({
    queryKey: ['ticker-backtests', sym],
    queryFn: () => tickerApi.backtests(sym),
    enabled: !!sym,
  })

  if (isLoading) {
    return (
      <div style={{ color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', fontSize: 13, padding: '40px 0' }}>
        Loading {sym}…
      </div>
    )
  }

  if (isError || !summary) {
    return (
      <div style={{ color: 'var(--color-danger)', fontFamily: 'var(--font-sans)', fontSize: 13, padding: '40px 0' }}>
        Ticker {sym} not found in watchlist.{' '}
        <Link to="/" style={{ color: 'var(--color-amber)' }}>Back to dashboard</Link>
      </div>
    )
  }

  const ts = summary.technicals
  const changeColor = pctColor(summary.daily_change_pct)
  const ChangeIcon = summary.daily_change_pct == null ? Minus
    : summary.daily_change_pct >= 0 ? TrendingUp : TrendingDown

  // Recharts tooltip
  const ChartTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    return (
      <div style={{ background: 'hsl(228 22% 10%)', border: '1px solid var(--color-border)', padding: '6px 10px', borderRadius: 6, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
        <div style={{ color: 'var(--color-text-muted)', marginBottom: 2 }}>{label}</div>
        <div style={{ color: 'var(--color-amber)' }}>${payload[0].value?.toFixed(2)}</div>
      </div>
    )
  }

  return (
    <div>
      {/* ── Back nav ── */}
      <Link
        to="/"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-muted)', textDecoration: 'none', marginBottom: 20 }}
      >
        <ArrowLeft size={12} />
        Dashboard
      </Link>

      {/* ── Header ── */}
      <div className="glass" style={{ padding: '20px 24px', marginBottom: 16 }}>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3" style={{ marginBottom: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 28, fontWeight: 700, color: 'var(--color-amber)' }}>
                {summary.symbol}
              </span>
              {summary.sector && (
                <span className="pill" style={{ background: 'hsl(228 15% 14%)', color: 'var(--color-text-muted)', border: '1px solid var(--color-border)', fontSize: 10 }}>
                  {summary.sector}
                </span>
              )}
            </div>
            <div style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--color-text-muted)' }}>
              {summary.name ?? sym}
            </div>
          </div>

          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 28, fontWeight: 500, color: 'var(--color-text-primary)', lineHeight: 1.1, marginBottom: 4 }}>
              {summary.latest_close != null ? `$${summary.latest_close.toFixed(2)}` : '—'}
            </div>
            {summary.daily_change_pct != null && (
              <div className="flex items-center gap-1 justify-end" style={{ color: changeColor, fontSize: 13, fontFamily: 'var(--font-mono)' }}>
                <ChangeIcon size={13} />
                <span>{summary.daily_change_pct >= 0 ? '+' : ''}{summary.daily_change_pct.toFixed(2)}%</span>
              </div>
            )}
            {summary.price_date && (
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: 10, color: 'var(--color-text-dim)', marginTop: 4 }}>
                as of {summary.price_date}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Price chart ── */}
      {priceHistory.length > 0 && (
        <div className="glass" style={{ padding: '20px 24px', marginBottom: 16 }}>
          <SectionHeader>90-Day Price</SectionHeader>
          <div style={{ height: 160 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={priceHistory} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="tickerGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(38 92% 55%)" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="hsl(38 92% 55%)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  tickFormatter={(d: string) => d.slice(5)} // MM-DD
                  tick={{ fontFamily: 'var(--font-mono)', fontSize: 9, fill: 'var(--color-text-dim)' }}
                  axisLine={false}
                  tickLine={false}
                  interval={Math.floor(priceHistory.length / 6)}
                />
                <YAxis
                  domain={['auto', 'auto']}
                  tick={{ fontFamily: 'var(--font-mono)', fontSize: 9, fill: 'var(--color-text-dim)' }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                />
                <Tooltip content={<ChartTooltip />} />
                <Area
                  type="monotone"
                  dataKey="close"
                  stroke="hsl(38 92% 55%)"
                  strokeWidth={1.5}
                  fill="url(#tickerGrad)"
                  dot={false}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── Technicals ── */}
      {ts && (
        <div className="glass" style={{ padding: '20px 24px', marginBottom: 16 }}>
          <SectionHeader>Technicals — {ts.date}</SectionHeader>
          <div className="flex gap-3" style={{ flexWrap: 'wrap' }}>
            <StatChip
              label="RSI 14"
              value={fmt(ts.rsi_14, 1)}
              color={ts.rsi_14 == null ? undefined : ts.rsi_14 < 35 ? 'var(--color-cyan)' : ts.rsi_14 > 70 ? 'var(--color-danger)' : 'var(--color-text-primary)'}
            />
            <StatChip
              label="MACD"
              value={ts.macd_direction === 'bull' ? 'Bullish' : 'Bearish'}
              color={ts.macd_direction === 'bull' ? 'var(--color-success)' : 'var(--color-danger)'}
            />
            <StatChip
              label="BB Position"
              value={ts.bb_position ?? '—'}
              color={ts.bb_position === 'above upper' ? 'var(--color-amber)' : ts.bb_position === 'below lower' ? 'var(--color-cyan)' : undefined}
            />
            <StatChip
              label="Vol vs 20d"
              value={ts.volume_ratio_20d != null ? `${ts.volume_ratio_20d.toFixed(1)}×` : '—'}
              color={ts.volume_ratio_20d != null && ts.volume_ratio_20d > 1.5 ? 'var(--color-amber)' : undefined}
            />
            <StatChip label="SMA 20"  value={fmt(ts.sma_20, 2, '')} />
            <StatChip label="SMA 50"  value={fmt(ts.sma_50, 2, '')} />
            <StatChip label="SMA 200" value={fmt(ts.sma_200, 2, '')} />
          </div>
        </div>
      )}

      {/* ── Middle row: Theses + Alerts ── */}
      <div className="flex gap-4" style={{ marginBottom: 16, alignItems: 'flex-start' }}>

        {/* Theses */}
        <div className="glass flex-1" style={{ padding: '20px 24px' }}>
          <SectionHeader>Linked Theses</SectionHeader>
          {theses.length === 0 ? (
            <div style={{ color: 'var(--color-text-dim)', fontSize: 12, fontFamily: 'var(--font-sans)' }}>
              No theses yet — ask the Thesis Lord to propose one.
            </div>
          ) : (
            theses.map(t => <ThesisRow key={t.id} thesis={t} />)
          )}
        </div>

        {/* Alerts */}
        <div className="glass" style={{ padding: '20px 24px', width: 280, flexShrink: 0 }}>
          <SectionHeader>Recent Alerts</SectionHeader>
          {alerts.length === 0 ? (
            <div style={{ color: 'var(--color-text-dim)', fontSize: 12, fontFamily: 'var(--font-sans)' }}>
              No alerts.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {alerts.slice(0, 10).map(a => (
                <div key={a.id} className="flex items-start gap-2" style={{ padding: '6px 0', borderBottom: '1px solid var(--color-border)' }}>
                  <AlertTriangle size={12} style={{ color: SEVERITY_COLOR[a.severity] ?? 'var(--color-text-muted)', flexShrink: 0, marginTop: 2 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-primary)' }}>
                      {ALERT_TYPE_LABEL[a.alert_type] ?? a.alert_type.replace(/_/g, ' ')}
                    </div>
                    {a.score != null && (
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-dim)' }}>
                        score {a.score.toFixed(0)}
                      </div>
                    )}
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--color-text-dim)', flexShrink: 0 }}>
                    {a.created_at ? new Date(a.created_at).toLocaleDateString() : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Backtests ── */}
      <div className="glass" style={{ padding: '20px 24px' }}>
        <SectionHeader>Backtest History</SectionHeader>
        {backtests.length === 0 ? (
          <div style={{ color: 'var(--color-text-dim)', fontSize: 12, fontFamily: 'var(--font-sans)' }}>
            No backtests yet — trigger one via the Thesis Lord in{' '}
            <Link to="/chat" style={{ color: 'var(--color-amber)' }}>Agent Chat</Link>.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr>
                {['Thesis', 'Sharpe', 'Sortino', 'Win %', 'Max DD', 'Trades', 'p-val', 'Run'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '4px 8px', fontFamily: 'var(--font-sans)', fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {backtests.map(bt => (
                <tr key={bt.id}>
                  <td style={{ padding: '6px 8px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {(bt as any).thesis_name ?? `#${bt.thesis_id}`}
                  </td>
                  <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: bt.sharpe != null && bt.sharpe > 1 ? 'var(--color-success)' : 'var(--color-text-primary)', borderBottom: '1px solid var(--color-border)' }}>
                    {fmt(bt.sharpe)}
                  </td>
                  <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)', borderBottom: '1px solid var(--color-border)' }}>
                    {fmt(bt.sortino)}
                  </td>
                  <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: bt.win_rate != null && bt.win_rate > 0.5 ? 'var(--color-success)' : 'var(--color-text-primary)', borderBottom: '1px solid var(--color-border)' }}>
                    {bt.win_rate != null ? `${(bt.win_rate * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: 'var(--color-danger)', borderBottom: '1px solid var(--color-border)' }}>
                    {bt.max_drawdown != null ? `${(bt.max_drawdown * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)', borderBottom: '1px solid var(--color-border)' }}>
                    {bt.total_trades ?? '—'}
                  </td>
                  <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: bt.monte_carlo_p_value != null && bt.monte_carlo_p_value < 0.05 ? 'var(--color-success)' : 'var(--color-text-dim)', borderBottom: '1px solid var(--color-border)' }}>
                    {fmt(bt.monte_carlo_p_value, 3)}
                  </td>
                  <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-dim)', borderBottom: '1px solid var(--color-border)' }}>
                    {bt.ran_at ? new Date(bt.ran_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
