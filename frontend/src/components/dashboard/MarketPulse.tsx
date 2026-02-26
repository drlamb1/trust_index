// Market Pulse — 6 macro metric cards
// Labels: Space Grotesk 10px muted caps
// Values: JetBrains Mono 32px white
// Change: ↑ amber / ↓ cyan / — muted

import { useQuery } from '@tanstack/react-query'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { simulation } from '@/lib/api'

interface MetricCard {
  label: string
  value: string
  change?: string
  direction?: 'up' | 'down' | 'flat'
  entryDelay: number
}

function PulseCard({ label, value, change, direction, entryDelay }: MetricCard) {
  const color = direction === 'up'
    ? 'var(--color-amber)'
    : direction === 'down'
    ? 'var(--color-cyan)'
    : 'var(--color-text-dim)'

  const Arrow = direction === 'up' ? TrendingUp : direction === 'down' ? TrendingDown : Minus

  return (
    <div
      className="glass animate-entry"
      style={{
        padding: '20px 24px',
        animationDelay: `${entryDelay}ms`,
        flex: '1 1 0',
        minWidth: 140,
      }}
    >
      <div style={{
        fontFamily: 'var(--font-sans)',
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        color: 'var(--color-text-muted)',
        marginBottom: 8,
      }}>
        {label}
      </div>
      <div style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 28,
        fontWeight: 500,
        color: 'var(--color-text-primary)',
        letterSpacing: '-0.02em',
        lineHeight: 1.1,
        marginBottom: 6,
      }}>
        {value}
      </div>
      {change && (
        <div className="flex items-center gap-1" style={{ color, fontSize: 12, fontFamily: 'var(--font-mono)' }}>
          <Arrow size={11} />
          <span>{change}</span>
        </div>
      )}
    </div>
  )
}

// Hardcoded market data for now — will connect to macro API
const PLACEHOLDER_METRICS: Omit<MetricCard, 'entryDelay'>[] = [
  { label: 'S&P 500', value: '—', change: '—', direction: 'flat' },
  { label: 'VIX', value: '—', change: '—', direction: 'flat' },
  { label: '10Y Yield', value: '—', change: '—', direction: 'flat' },
  { label: 'Fed Funds', value: '—', change: '—', direction: 'flat' },
  { label: 'DXY', value: '—', change: '—', direction: 'flat' },
  { label: 'BTC', value: '—', change: '—', direction: 'flat' },
]

export default function MarketPulse() {
  return (
    <section>
      <h2 style={{
        fontFamily: 'var(--font-sans)',
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        color: 'var(--color-text-muted)',
        marginBottom: 12,
      }}>
        Market Pulse
      </h2>
      <div className="flex gap-3" style={{ flexWrap: 'wrap' }}>
        {PLACEHOLDER_METRICS.map((m, i) => (
          <PulseCard key={m.label} {...m} entryDelay={i * 60} />
        ))}
      </div>
    </section>
  )
}
