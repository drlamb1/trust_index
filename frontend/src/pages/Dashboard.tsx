// Dashboard — the void with eyes
// Market Pulse | Thesis Constellation + Simulation Engine | Intelligence Feed + Agent Console

import { useState } from 'react'
import MarketPulse from '@/components/dashboard/MarketPulse'
import ThesisConstellation from '@/components/dashboard/ThesisConstellation'
import SimulationEngine from '@/components/dashboard/SimulationEngine'
import IntelligenceFeed from '@/components/dashboard/IntelligenceFeed'
import AgentConsole from '@/components/dashboard/AgentConsole'
import type { SimulatedThesis } from '@/types/api'

export default function Dashboard() {
  const [_selectedThesis, setSelectedThesis] = useState<SimulatedThesis | null>(null)

  return (
    <div className="flex flex-col gap-4">
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
    </div>
  )
}
