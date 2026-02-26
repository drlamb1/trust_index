// Simulation Engine panel — 4 stats + P&L sparkline + PLAY MONEY badge
// Stats: SIM P&L (amber), WIN RATE, SHARPE, ACTIVE THESES
// Sparkline: amber AreaChart, no axes, just the shape

import { useQuery } from '@tanstack/react-query'
import { DollarSign, Target, TrendingUp, Activity } from 'lucide-react'
import { AreaChart, Area, ResponsiveContainer } from 'recharts'
import { simulation } from '@/lib/api'
import type { SimulationStats } from '@/types/api'

function StatTile({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: React.ComponentType<{ size: number }>
  label: string
  value: string
  accent?: boolean
}) {
  return (
    <div className="glass-sm flex items-center gap-3" style={{ padding: '12px 16px' }}>
      <div
        className="flex items-center justify-center rounded-lg flex-shrink-0"
        style={{
          width: 36,
          height: 36,
          background: accent ? 'var(--color-amber-muted)' : 'hsl(228 15% 14%)',
          border: `1px solid ${accent ? 'var(--color-amber-dim)' : 'var(--color-border)'}`,
        }}
      >
        <Icon size={14} />
      </div>
      <div>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: 10, color: 'var(--color-text-muted)', letterSpacing: '0.05em', textTransform: 'uppercase', fontWeight: 600 }}>
          {label}
        </div>
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 20,
          fontWeight: 500,
          color: accent ? 'var(--color-amber)' : 'var(--color-text-primary)',
          lineHeight: 1.2,
        }}>
          {value}
        </div>
      </div>
    </div>
  )
}

// Sparkline data — placeholder until we connect historical P&L API
const SPARKLINE = Array.from({ length: 30 }, (_, i) => ({
  v: 100000 + Math.sin(i * 0.4) * 3000 + i * 400 + Math.random() * 1000,
}))

export default function SimulationEngine() {
  const { data: stats } = useQuery({
    queryKey: ['simulation-stats'],
    queryFn: simulation.stats,
    refetchInterval: 60_000,
  })

  const pnl = stats?.portfolio?.pnl ?? 0
  const pnlPct = stats?.portfolio?.pnl_pct ?? 0
  const activeTheses = stats?.theses?.by_status?.paper_live ?? 0
  const winRateStr = stats?.avg_win_rate != null
    ? `${(stats.avg_win_rate * 100).toFixed(1)}%`
    : '—'
  const sharpeStr = stats?.avg_sharpe != null
    ? stats.avg_sharpe.toFixed(2)
    : '—'

  return (
    <div className="glass animate-entry animate-entry-2" style={{ padding: '20px 24px', height: '100%' }}>
      {/* Header */}
      <div className="flex items-center justify-between" style={{ marginBottom: 16 }}>
        <h2 style={{
          fontFamily: 'var(--font-sans)',
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--color-text-muted)',
        }}>
          Simulation Engine
        </h2>
        <span className="pill pill-amber">Play Money</span>
      </div>

      {/* 4 stat tiles */}
      <div className="grid grid-cols-2 gap-2" style={{ marginBottom: 16 }}>
        <StatTile
          icon={DollarSign}
          label="Sim P&L"
          value={pnl >= 0 ? `+$${Math.abs(pnl).toLocaleString('en-US', { maximumFractionDigits: 0 })}` : `-$${Math.abs(pnl).toLocaleString('en-US', { maximumFractionDigits: 0 })}`}
          accent
        />
        <StatTile
          icon={Target}
          label="Win Rate"
          value={winRateStr}
        />
        <StatTile
          icon={TrendingUp}
          label="Sharpe"
          value={sharpeStr}
        />
        <StatTile
          icon={Activity}
          label="Active Theses"
          value={String(activeTheses)}
        />
      </div>

      {/* P&L sparkline — amber, no axes */}
      <div style={{ height: 64 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={SPARKLINE} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="amberGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="hsl(38 92% 55%)" stopOpacity={0.25} />
                <stop offset="95%" stopColor="hsl(38 92% 55%)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area
              type="monotone"
              dataKey="v"
              stroke="hsl(38 92% 55%)"
              strokeWidth={1.5}
              fill="url(#amberGrad)"
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
