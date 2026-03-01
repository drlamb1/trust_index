// Simulation Lab — full constellation + vol surface + Heston + portfolio

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ThesisConstellation from '@/components/dashboard/ThesisConstellation'
import VolSurfaceHeatmap from '@/components/simulation/VolSurfaceHeatmap'
import DecisionLog from '@/components/simulation/DecisionLog'
import MLModelStatus from '@/components/simulation/MLModelStatus'
import { simulation } from '@/lib/api'
import type { SimulatedThesis, HestonParams, VolSurface } from '@/types/api'
import { ChevronDown, ChevronUp } from 'lucide-react'

// ─── Heston Params Panel ───

function HestonPanel({ ticker }: { ticker: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['heston', ticker],
    queryFn: () => simulation.heston(ticker),
    enabled: !!ticker,
  })

  const params = [
    { key: 'v0', label: 'v₀', desc: 'Current variance. √v₀ ≈ current vol.' },
    { key: 'kappa', label: 'κ', desc: 'Mean-reversion speed. High = fast snap back.' },
    { key: 'theta', label: 'θ', desc: 'Long-run variance. √θ = long-run vol.' },
    { key: 'sigma_v', label: 'σᵥ', desc: 'Vol-of-vol. Higher = fatter tails.' },
    { key: 'rho', label: 'ρ', desc: 'Price/vol correlation. Negative = put skew (leverage effect).' },
  ] as const

  if (isLoading) return <div style={{ color: 'var(--color-text-dim)', fontSize: 11 }}>Loading Heston params…</div>
  if (!data || 'message' in data) return (
    <div style={{ color: 'var(--color-text-dim)', fontSize: 11 }}>
      No Heston calibration for {ticker}. Options data needed first.
    </div>
  )

  return (
    <div>
      <div className="grid grid-cols-5 gap-2" style={{ marginBottom: 8 }}>
        {params.map(({ key, label, desc }) => (
          <div
            key={key}
            className="glass-sm text-center"
            title={desc}
            style={{ padding: '10px 8px', cursor: 'help' }}
          >
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
              {label}
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 600, color: 'var(--color-cyan)' }}>
              {(data as HestonParams)[key].toFixed(3)}
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <span
          className="pill"
          style={
            (data as HestonParams).feller_satisfied
              ? { background: 'hsl(142 40% 12%)', color: 'var(--color-success)', border: '1px solid hsl(142 40% 25%)' }
              : { background: 'var(--color-amber-muted)', color: 'var(--color-amber)', border: '1px solid var(--color-amber-dim)' }
          }
        >
          Feller: {(data as HestonParams).feller_satisfied ? 'Satisfied' : 'Violated — QE handles this'}
        </span>
        {(data as HestonParams).calibration_error && (
          <span style={{ fontSize: 10, color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)' }}>
            RMSE: {((data as HestonParams).calibration_error! * 100).toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Thesis Drawer ───

function ThesisDrawer({ thesis, onClose }: { thesis: SimulatedThesis; onClose: () => void }) {
  const STATUS_COLOR: Record<string, string> = {
    proposed: 'var(--color-text-muted)',
    backtesting: 'var(--color-amber)',
    paper_live: 'var(--color-success)',
    retired: 'var(--color-text-dim)',
    killed: 'var(--color-danger)',
  }

  return (
    <div
      className="glass"
      style={{
        position: 'fixed', right: 24, top: 80, bottom: 24, width: 400,
        overflowY: 'auto', zIndex: 100, padding: '24px',
      }}
    >
      <div className="flex items-start justify-between" style={{ marginBottom: 16 }}>
        <div>
          <h2 style={{ fontFamily: 'var(--font-sans)', fontSize: 16, fontWeight: 600, color: 'var(--color-text-primary)' }}>
            {thesis.name}
          </h2>
          <span
            className="pill"
            style={{ background: STATUS_COLOR[thesis.status] + '20', color: STATUS_COLOR[thesis.status], border: `1px solid ${STATUS_COLOR[thesis.status]}40`, marginTop: 6 }}
          >
            {thesis.status.replace('_', ' ')}
          </span>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', fontSize: 18 }}>
          ×
        </button>
      </div>

      <div style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.7, marginBottom: 20 }}>
        {thesis.thesis_text}
      </div>

      {thesis.risk_factors && thesis.risk_factors.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-danger)', marginBottom: 8 }}>
            Risk Factors
          </div>
          {thesis.risk_factors.map((r, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--color-text-muted)', padding: '4px 0', borderBottom: '1px solid var(--color-border)', fontFamily: 'var(--font-sans)' }}>
              {r}
            </div>
          ))}
        </div>
      )}

      {thesis.expected_catalysts && thesis.expected_catalysts.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-amber)', marginBottom: 8 }}>
            Expected Catalysts
          </div>
          {thesis.expected_catalysts.map((c, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--color-text-muted)', padding: '4px 0', borderBottom: '1px solid var(--color-border)', fontFamily: 'var(--font-sans)' }}>
              {c}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Portfolio Table ───

function PaperPortfolioTable() {
  const { data } = useQuery({
    queryKey: ['portfolio'],
    queryFn: simulation.portfolio,
    refetchInterval: 30_000,
  })

  return (
    <div>
      <div className="flex items-center gap-2" style={{ marginBottom: 12 }}>
        <h3 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
          Paper Portfolio
        </h3>
        <span className="pill pill-amber">Play Money</span>
        {data && (
          <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, color: data.total_pnl >= 0 ? 'var(--color-amber)' : 'var(--color-danger)' }}>
            {data.total_pnl >= 0 ? '+' : ''}${data.total_pnl.toLocaleString('en-US', { maximumFractionDigits: 0 })}
          </span>
        )}
      </div>

      {!data?.positions?.length ? (
        <div style={{ color: 'var(--color-text-dim)', fontSize: 11, fontFamily: 'var(--font-sans)', lineHeight: 1.6 }}>
          <div>No open positions yet.</div>
          <div style={{ marginTop: 4, fontSize: 10 }}>
            Flow: Thesis generated → backtested → survivors (positive Sharpe) get promoted to PAPER_LIVE → positions opened here with simulated capital.
          </div>
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr>
              {['Ticker', 'Thesis', 'Side', 'Entry', 'Current', 'P&L'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '4px 8px', fontFamily: 'var(--font-sans)', fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.positions.map(pos => (
              <tr key={pos.id}>
                <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--color-amber)', borderBottom: '1px solid var(--color-border)' }}>{pos.ticker}</td>
                <td style={{ padding: '6px 8px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pos.thesis}</td>
                <td style={{ padding: '6px 8px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)', textTransform: 'capitalize' }}>{pos.side}</td>
                <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)', borderBottom: '1px solid var(--color-border)' }}>${pos.entry_price.toFixed(2)}</td>
                <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)', borderBottom: '1px solid var(--color-border)' }}>${pos.current_price.toFixed(2)}</td>
                <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: pos.unrealized_pnl >= 0 ? 'var(--color-amber)' : 'var(--color-danger)', borderBottom: '1px solid var(--color-border)' }}>
                  {pos.unrealized_pnl >= 0 ? '+' : ''}{(pos.unrealized_pnl_pct * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ─── Main Page ───

export default function SimulationLab() {
  const [selectedThesis, setSelectedThesis] = useState<SimulatedThesis | null>(null)
  const [hestonTicker, setHestonTicker] = useState('NVDA')

  return (
    <div>
      {/* Full constellation */}
      <div style={{ marginBottom: 16 }}>
        <ThesisConstellation height={500} onThesisSelect={setSelectedThesis} />
      </div>

      {/* Bottom panels */}
      <div className="flex gap-4" style={{ alignItems: 'flex-start' }}>
        {/* Heston */}
        <div className="glass flex-1" style={{ padding: '20px 24px' }}>
          <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
            <h3 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
              Heston Calibration
            </h3>
            <select
              value={hestonTicker}
              onChange={e => setHestonTicker(e.target.value)}
              style={{
                background: 'hsl(228 15% 14%)', border: '1px solid var(--color-border)',
                color: 'var(--color-text-primary)', borderRadius: 6,
                padding: '2px 8px', fontSize: 11, fontFamily: 'var(--font-mono)',
                outline: 'none', cursor: 'pointer',
              }}
            >
              {['NVDA', 'MSFT', 'AAPL', 'AMZN', 'META', 'GOOGL'].map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <HestonPanel ticker={hestonTicker} />
        </div>

        {/* Vol Surface */}
        <div className="glass flex-1" style={{ padding: '20px 24px' }}>
          <h3 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 12 }}>
            Volatility Surface
          </h3>
          <VolSurfaceHeatmap ticker={hestonTicker} />
        </div>

        {/* Paper Portfolio */}
        <div className="glass flex-1" style={{ padding: '20px 24px' }}>
          <PaperPortfolioTable />
        </div>
      </div>

      {/* Decision Log + ML Models */}
      <div className="flex gap-4" style={{ alignItems: 'flex-start', marginTop: 16 }}>
        <div className="glass" style={{ padding: '20px 24px', flex: 2 }}>
          <DecisionLog />
        </div>
        <div className="glass" style={{ padding: '20px 24px', flex: 1 }}>
          <MLModelStatus />
        </div>
      </div>

      {/* Thesis drawer */}
      {selectedThesis && (
        <ThesisDrawer thesis={selectedThesis} onClose={() => setSelectedThesis(null)} />
      )}
    </div>
  )
}
