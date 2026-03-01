// Dashboard — the void with eyes
// Market Pulse | Thesis Constellation + Simulation Engine | Intelligence Feed + Agent Console

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { X, BarChart2 } from 'lucide-react'
import MarketPulse from '@/components/dashboard/MarketPulse'
import ThesisConstellation from '@/components/dashboard/ThesisConstellation'
import SimulationEngine from '@/components/dashboard/SimulationEngine'
import IntelligenceFeed from '@/components/dashboard/IntelligenceFeed'
import AgentConsole from '@/components/dashboard/AgentConsole'
import WelcomeOverlay from '@/components/onboarding/WelcomeOverlay'
import type { SimulatedThesis } from '@/types/api'

const STATUS_COLOR: Record<string, string> = {
  proposed:    'var(--color-text-muted)',
  backtesting: 'var(--color-amber)',
  paper_live:  'var(--color-success)',
  retired:     'var(--color-text-dim)',
  killed:      'var(--color-danger)',
}

function ThesisDrawer({ thesis, onClose }: { thesis: SimulatedThesis; onClose: () => void }) {
  const navigate = useNavigate()
  const color = STATUS_COLOR[thesis.status] ?? 'var(--color-text-muted)'

  return (
    <div
      className="glass"
      style={{
        position: 'fixed', right: 24, top: 72, bottom: 24, width: 380,
        overflowY: 'auto', zIndex: 100, padding: '24px',
        boxShadow: '0 0 40px hsl(228 22% 5% / 0.8)',
      }}
    >
      <div className="flex items-start justify-between" style={{ marginBottom: 16 }}>
        <div style={{ flex: 1, minWidth: 0, paddingRight: 12 }}>
          <h2 style={{ fontFamily: 'var(--font-sans)', fontSize: 15, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 6 }}>
            {thesis.name}
          </h2>
          <div className="flex items-center gap-2">
            <span className="pill" style={{ background: color + '20', color, border: `1px solid ${color}40` }}>
              {thesis.status.replace('_', ' ')}
            </span>
            {thesis.ticker_symbol && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-amber)', fontWeight: 600 }}>
                {thesis.ticker_symbol}
              </span>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', padding: 4 }}
        >
          <X size={16} />
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
        <div style={{ marginBottom: 20 }}>
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

      <div className="flex flex-col gap-2">
        {thesis.ticker_symbol && (
          <button
            onClick={() => { navigate(`/tickers/${thesis.ticker_symbol}`); onClose() }}
            className="flex items-center gap-2"
            style={{
              background: 'var(--color-amber-muted)', border: '1px solid var(--color-amber-dim)',
              color: 'var(--color-amber)', borderRadius: 8, padding: '10px 16px',
              fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 600,
              cursor: 'pointer', width: '100%', justifyContent: 'center',
            }}
          >
            <BarChart2 size={13} />
            View Ticker — {thesis.ticker_symbol}
          </button>
        )}
        <Link
          to={`/chat?persona=thesis_lord&message=${encodeURIComponent(`What's the current status of thesis "${thesis.name}" (ID ${thesis.id})? Give me the full picture.`)}`}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'hsl(228 15% 14%)', border: '1px solid var(--color-border)',
            color: 'var(--color-text-muted)', borderRadius: 8, padding: '10px 16px',
            fontFamily: 'var(--font-sans)', fontSize: 12, textDecoration: 'none',
          }}
        >
          Open in Thesis Lord
        </Link>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [selectedThesis, setSelectedThesis] = useState<SimulatedThesis | null>(null)
  const [showOnboarding, setShowOnboarding] = useState(
    () => !localStorage.getItem('ef_onboarding_done')
  )

  const dismissOnboarding = () => {
    localStorage.setItem('ef_onboarding_done', '1')
    setShowOnboarding(false)
  }

  return (
    <div className="flex flex-col gap-4">
      {showOnboarding && <WelcomeOverlay onDismiss={dismissOnboarding} />}
      {/* Market Pulse — top strip */}
      <MarketPulse />

      {/* Middle row — Constellation (55%) + Simulation Engine (45%) */}
      <div className="flex gap-4" style={{ alignItems: 'stretch' }}>
        <div style={{ flex: '0 0 55%' }}>
          <ThesisConstellation
            height={420}
            onThesisSelect={setSelectedThesis}
          />
        </div>
        <div style={{ flex: '0 0 calc(45% - 16px)' }}>
          <SimulationEngine />
        </div>
      </div>

      {/* Bottom row — Intelligence Feed (55%) + Agent Console (45%) */}
      <div className="flex gap-4">
        <div style={{ flex: '0 0 55%' }}>
          <IntelligenceFeed />
        </div>
        <div style={{ flex: '0 0 calc(45% - 16px)' }}>
          <AgentConsole />
        </div>
      </div>

      {selectedThesis && (
        <ThesisDrawer
          thesis={selectedThesis}
          onClose={() => setSelectedThesis(null)}
        />
      )}
    </div>
  )
}
