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

const INTEL_EVENTS = ['thesis_created', 'backtest_complete', 'position_opened', 'position_closed', 'signal_detected', 'thesis_killed', 'DAILY_BRIEFING']
const SYSTEM_EVENT_TYPES = ['pr_merge', 'BACKTEST_START', 'BACKTEST_COMPLETE']

type MetaFilter = 'Intelligence' | 'System' | 'All'
const META_FILTERS: MetaFilter[] = ['Intelligence', 'System', 'All']

function metaFilterToEventTypes(meta: MetaFilter): string[] | undefined {
  switch (meta) {
    case 'Intelligence': return INTEL_EVENTS
    case 'System': return SYSTEM_EVENT_TYPES
    case 'All': return undefined
  }
}

export default function DecisionLog() {
  const [metaFilter, setMetaFilter] = useState<MetaFilter>('Intelligence')
  const [detailFilter, setDetailFilter] = useState<string | null>(null)
  const [limit, setLimit] = useState(30)

  // When a detail filter is active, use it directly; otherwise expand the meta-filter
  const activeEventType = detailFilter ?? undefined
  const allowedTypes = metaFilterToEventTypes(metaFilter)

  const { data: entries = [] } = useQuery({
    queryKey: ['decision-log', metaFilter, detailFilter, limit],
    queryFn: () => simulation.decisionLog({
      event_type: activeEventType,
      limit,
    }),
    refetchInterval: 60_000,
    select: (data) => {
      // Client-side filter when using meta-filter (no detail filter)
      if (!detailFilter && allowedTypes) {
        return data.filter((e: SimulationLog) => allowedTypes.includes(e.event_type))
      }
      return data
    },
  })

  const detailPills = metaFilter === 'Intelligence' ? INTEL_EVENTS
    : metaFilter === 'System' ? SYSTEM_EVENT_TYPES
    : [...INTEL_EVENTS, ...SYSTEM_EVENT_TYPES]

  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <h3 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
          Decision Log
        </h3>
      </div>

      {/* Meta-filter row */}
      <div className="flex gap-1 flex-wrap" style={{ marginBottom: 6 }}>
        {META_FILTERS.map(f => (
          <button
            key={f}
            onClick={() => { setMetaFilter(f); setDetailFilter(null) }}
            className="pill"
            style={{
              cursor: 'pointer',
              background: metaFilter === f ? 'var(--color-amber-muted)' : 'hsl(228 15% 14%)',
              color: metaFilter === f ? 'var(--color-amber)' : 'var(--color-text-dim)',
              border: `1px solid ${metaFilter === f ? 'var(--color-amber-dim)' : 'var(--color-border)'}`,
              fontWeight: 600,
            }}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Detail filter row */}
      <div className="flex gap-1 flex-wrap" style={{ marginBottom: 12 }}>
        {detailPills.map(t => (
          <button
            key={t}
            onClick={() => setDetailFilter(detailFilter === t ? null : t)}
            className="pill"
            style={{
              cursor: 'pointer',
              background: detailFilter === t ? 'var(--color-amber-muted)' : 'hsl(228 15% 14%)',
              color: detailFilter === t ? 'var(--color-amber)' : 'var(--color-text-dim)',
              border: `1px solid ${detailFilter === t ? 'var(--color-amber-dim)' : 'var(--color-border)'}`,
              fontSize: 9,
            }}
          >
            {t.replace(/_/g, ' ')}
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
