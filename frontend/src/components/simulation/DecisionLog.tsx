// Decision Log — paginated view of SimulationLog entries
// Filterable by event type, expandable JSON details

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { simulation } from '@/lib/api'
import { agentColor } from '@/lib/personas'
import { timeAgo } from '@/lib/timeAgo'
import type { SimulationLog } from '@/types/api'

function LogEntry({ entry }: { entry: SimulationLog }) {
  const [open, setOpen] = useState(false)
  const hasData = entry.event_data && Object.keys(entry.event_data).length > 0

  return (
    <div style={{ padding: '6px 0', borderBottom: '1px solid var(--color-border)' }}>
      <div className="flex items-center gap-2" style={{ fontSize: 11 }}>
        <div style={{
          width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
          background: agentColor(entry.agent_name),
        }} />
        <span style={{ fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', minWidth: 70 }}>
          {entry.agent_name}
        </span>
        <span style={{ fontFamily: 'var(--font-sans)', color: 'var(--color-text-primary)', flex: 1 }}>
          {entry.event_type.replace(/_/g, ' ')}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-dim)', flexShrink: 0 }}>
          {timeAgo(entry.created_at)}
        </span>
        {hasData && (
          <button
            onClick={() => setOpen(!open)}
            style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--color-text-dim)', padding: 2 }}
          >
            {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        )}
      </div>
      {open && hasData && (
        <pre style={{
          margin: '6px 0 0 14px', padding: '6px 10px',
          fontSize: 10, fontFamily: 'var(--font-mono)',
          color: 'var(--color-text-dim)', background: 'hsl(228 15% 10%)',
          borderRadius: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {JSON.stringify(entry.event_data, null, 2)}
        </pre>
      )}
    </div>
  )
}

const EVENT_TYPES = ['All', 'thesis_created', 'backtest_complete', 'position_opened', 'position_closed', 'signal_detected', 'thesis_killed', 'DAILY_BRIEFING', 'pr_merge', 'BACKTEST_START', 'BACKTEST_COMPLETE']

export default function DecisionLog() {
  const [filter, setFilter] = useState('All')
  const [limit, setLimit] = useState(30)

  const { data: entries = [] } = useQuery({
    queryKey: ['decision-log', filter, limit],
    queryFn: () => simulation.decisionLog({
      event_type: filter === 'All' ? undefined : filter,
      limit,
    }),
    refetchInterval: 60_000,
  })

  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <h3 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
          Decision Log
        </h3>
      </div>

      {/* Filter pills */}
      <div className="flex gap-1 flex-wrap" style={{ marginBottom: 12 }}>
        {EVENT_TYPES.map(t => (
          <button
            key={t}
            onClick={() => setFilter(t)}
            className="pill"
            style={{
              cursor: 'pointer', border: 'none',
              background: filter === t ? 'var(--color-amber-muted)' : 'hsl(228 15% 14%)',
              color: filter === t ? 'var(--color-amber)' : 'var(--color-text-dim)',
            }}
          >
            {t === 'All' ? 'All' : t.replace(/_/g, ' ')}
          </button>
        ))}
      </div>

      {/* Log entries */}
      <div style={{ maxHeight: 300, overflowY: 'auto' }}>
        {entries.length === 0 && (
          <div style={{ fontSize: 11, color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)' }}>
            No decision log entries yet.
          </div>
        )}
        {entries.map(entry => (
          <LogEntry key={entry.id} entry={entry} />
        ))}
      </div>

      {entries.length >= limit && (
        <button
          onClick={() => setLimit(l => l + 30)}
          style={{
            background: 'transparent', border: '1px solid var(--color-border)',
            borderRadius: 6, padding: '4px 12px', cursor: 'pointer',
            fontFamily: 'var(--font-mono)', fontSize: 10,
            color: 'var(--color-text-dim)', marginTop: 8,
            display: 'block', width: '100%',
          }}
        >
          Load more
        </button>
      )}
    </div>
  )
}
