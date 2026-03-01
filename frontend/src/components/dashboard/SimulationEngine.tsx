// Simulation Engine panel — 4 stats + portfolio summary + PLAY MONEY badge

import { useQuery } from '@tanstack/react-query'
import { DollarSign, Target, TrendingUp, Activity } from 'lucide-react'
import { simulation } from '@/lib/api'

function StatTile({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: React.ComponentType<{ size: number; style?: React.CSSProperties }>
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
        <Icon size={14} style={{ color: accent ? 'var(--color-amber)' : 'var(--color-text-dim)' }} />
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

export default function SimulationEngine() {
  const { data: stats, isError } = useQuery({
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

      {isError && (
        <div style={{ fontSize: 11, color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', marginBottom: 8 }}>
          Simulation stats unavailable — will retry automatically.
        </div>
      )}

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

      {/* Portfolio summary */}
      <div className="glass-sm" style={{ padding: '10px 16px' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-dim)' }}>
          Portfolio: ${stats?.portfolio?.value?.toLocaleString('en-US', { maximumFractionDigits: 0 }) ?? '—'}
          {' · '}{stats?.theses?.total ?? 0} theses tracked
          {pnlPct !== 0 && (
            <span style={{ color: pnlPct >= 0 ? 'var(--color-amber)' : 'var(--color-danger)', marginLeft: 8 }}>
              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(1)}%
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
