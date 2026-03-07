// Intelligence Feed — SSE-driven narrative alerts
// Icon encoding type, ticker badge, one-line story, timestamp
// Visual tiering: intelligence events full-color, system events dimmed

import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Zap, AlertTriangle, FileSearch, BarChart2, TrendingDown, Info, BookOpen, GitMerge, ChevronDown, ChevronUp } from 'lucide-react'
import { createSimulationStream } from '@/lib/sse'
import { agentColor } from '@/lib/personas'
import { timeAgo } from '@/lib/timeAgo'

interface FeedItem {
  id: number
  agent_name: string
  event_type: string
  event_data: Record<string, unknown> | null
  created_at: string
}

const SYSTEM_EVENTS = new Set(['pr_merge', 'BACKTEST_START', 'BACKTEST_COMPLETE'])

function isSystemEvent(eventType: string) {
  return SYSTEM_EVENTS.has(eventType)
}

function typeIcon(eventType: string) {
  if (eventType === 'DAILY_BRIEFING') return BookOpen
  if (eventType === 'pr_merge') return GitMerge
  if (eventType.includes('volume') || eventType.includes('spike')) return Zap
  if (eventType.includes('anomaly') || eventType.includes('alert')) return AlertTriangle
  if (eventType.includes('filing') || eventType.includes('post_mortem')) return FileSearch
  if (eventType.includes('thesis') || eventType.includes('backtest')) return BarChart2
  if (eventType.includes('stop') || eventType.includes('exit')) return TrendingDown
  return Info
}

function formatLine(item: FeedItem): string {
  const data = item.event_data ?? {}
  if (data.ticker) return `${data.ticker}: ${item.event_type.replace(/_/g, ' ')}`
  if (data.thesis_name) return `"${data.thesis_name}" — ${item.event_type.replace(/_/g, ' ')}`
  if (data.reason) return String(data.reason).slice(0, 80)
  return item.event_type.replace(/_/g, ' ')
}

/** Route click to the appropriate page based on event type */
function eventRoute(item: FeedItem): string | null {
  const ticker = item.event_data?.ticker as string | undefined
  switch (item.event_type) {
    case 'DAILY_BRIEFING': return '/briefing'
    case 'thesis_created': return '/chat?persona=thesis_lord&message=Tell me about the latest thesis'
    case 'backtest_complete': return '/simulation'
    case 'signal_detected':
    case 'position_opened':
    case 'position_closed':
    case 'thesis_killed':
      return ticker ? `/tickers/${ticker}` : '/simulation'
    default:
      return ticker ? `/tickers/${ticker}` : null
  }
}

/** Group consecutive system events for collapsing */
function groupItems(items: FeedItem[]): Array<FeedItem | { collapsed: true; items: FeedItem[] }> {
  const result: Array<FeedItem | { collapsed: true; items: FeedItem[] }> = []
  let systemBuffer: FeedItem[] = []

  const flushBuffer = () => {
    if (systemBuffer.length > 3) {
      result.push({ collapsed: true, items: [...systemBuffer] })
    } else {
      result.push(...systemBuffer)
    }
    systemBuffer = []
  }

  for (const item of items) {
    if (isSystemEvent(item.event_type)) {
      systemBuffer.push(item)
    } else {
      flushBuffer()
      result.push(item)
    }
  }
  flushBuffer()
  return result
}

export default function IntelligenceFeed() {
  const navigate = useNavigate()
  const [items, setItems] = useState<FeedItem[]>([])
  const [connected, setConnected] = useState(false)
  const [timedOut, setTimedOut] = useState(false)
  const [expandedSystem, setExpandedSystem] = useState(false)
  const connectedRef = useRef(false)

  useEffect(() => {
    const timeout = setTimeout(() => {
      if (!connectedRef.current) setTimedOut(true)
    }, 15_000)

    const close = createSimulationStream(
      (event) => {
        if ((event as any).type === 'connected') {
          connectedRef.current = true
          setConnected(true)
          setTimedOut(false)
          return
        }
        setItems(prev => [event as unknown as FeedItem, ...prev].slice(0, 50))
      },
      () => { connectedRef.current = false; setConnected(false) },
    )
    return () => { close(); clearTimeout(timeout) }
  }, [])

  // Dashboard feed hides system events entirely; Simulation Lab Decision Log has the full view
  const intelligenceItems = items.filter(i => !isSystemEvent(i.event_type))
  const systemCount = items.length - intelligenceItems.length
  const grouped = groupItems(intelligenceItems)
  const hasOnlySystemEvents = items.length > 0 && intelligenceItems.length === 0

  return (
    <div className="glass animate-entry animate-entry-4" style={{ padding: '20px 24px' }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <div className="flex items-center gap-2">
          <h2 style={{
            fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600,
            letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--color-text-muted)',
          }}>
            Intelligence Feed
          </h2>
          <div
            style={{
              width: 6, height: 6, borderRadius: '50%',
              background: connected ? 'var(--color-success)' : 'var(--color-text-dim)',
            }}
          />
        </div>
        <Link
          to="/simulation"
          style={{ fontSize: 11, color: 'var(--color-amber)', textDecoration: 'none', fontFamily: 'var(--font-sans)' }}
        >
          View all →
        </Link>
      </div>

      <div className="flex flex-col gap-1" style={{ maxHeight: 200, overflowY: 'auto' }}>
        {items.length === 0 && (
          <div style={{ color: 'var(--color-text-dim)', fontSize: 11, padding: '8px 0' }}>
            {connected ? 'Waiting for agent activity…' : timedOut ? 'Feed unavailable — backend may be starting up.' : 'Connecting to feed…'}
          </div>
        )}

        {/* System event count — visible but not polluting the feed */}
        {systemCount > 0 && intelligenceItems.length > 0 && (
          <div style={{
            color: 'var(--color-text-dim)', fontSize: 10, padding: '2px 0', marginBottom: 2,
            fontFamily: 'var(--font-mono)', opacity: 0.5,
          }}>
            {systemCount} system event{systemCount !== 1 ? 's' : ''} hidden · <Link to="/simulation" style={{ color: 'var(--color-text-dim)', textDecoration: 'underline' }}>view in Decision Log</Link>
          </div>
        )}

        {/* Pipeline warming notice: connected but only system events */}
        {hasOnlySystemEvents && (
          <div style={{
            color: 'var(--color-text-muted)', fontSize: 11, padding: '6px 8px', marginBottom: 4,
            background: 'hsl(228 15% 12%)', borderRadius: 6, fontFamily: 'var(--font-sans)',
            borderLeft: '2px solid var(--color-amber-dim)',
          }}>
            Intelligence pipeline is syncing data. Signals will appear as the system detects thesis-worthy patterns.
          </div>
        )}

        {grouped.map((entry, i) => {
          // Collapsed system events group
          if ('collapsed' in entry) {
            return (
              <div key={`sys-${i}`}>
                <button
                  onClick={() => setExpandedSystem(!expandedSystem)}
                  className="flex items-center gap-2 w-full"
                  style={{
                    padding: '4px 0', fontSize: 10, background: 'transparent', border: 'none',
                    cursor: 'pointer', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)',
                    opacity: 0.6,
                  }}
                >
                  <GitMerge size={10} />
                  <span>{entry.items.length} system events</span>
                  {expandedSystem ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                </button>
                {expandedSystem && entry.items.map((item, j) => (
                  <FeedRow key={`${item.id}-${j}`} item={item} navigate={navigate} />
                ))}
              </div>
            )
          }

          // Regular event row
          return <FeedRow key={`${entry.id}-${i}`} item={entry} navigate={navigate} />
        })}
      </div>
    </div>
  )
}

function FeedRow({ item, navigate }: { item: FeedItem; navigate: ReturnType<typeof useNavigate> }) {
  const Icon = typeIcon(item.event_type)
  const system = isSystemEvent(item.event_type)
  const route = eventRoute(item)
  const ticker = item.event_data?.ticker as string | undefined

  return (
    <div
      className="flex items-start gap-2"
      onClick={() => route && navigate(route)}
      style={{
        padding: '6px 0', borderBottom: '1px solid var(--color-border)',
        fontSize: system ? 10 : 11,
        cursor: route ? 'pointer' : 'default',
        opacity: system ? 0.45 : 1,
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => { if (route) (e.currentTarget.style.background = 'hsl(228 15% 12%)') }}
      onMouseLeave={e => { e.currentTarget.style.background = '' }}
    >
      <Icon size={12} style={{ color: agentColor(item.agent_name), flexShrink: 0, marginTop: 2 }} />
      <div className="flex-1 min-w-0">
        {ticker && (
          <span
            className="pill"
            style={{
              background: 'var(--color-amber-muted)',
              color: 'var(--color-amber)',
              border: '1px solid var(--color-amber-dim)',
              marginRight: 6,
              fontSize: 9,
            }}
          >
            {ticker}
          </span>
        )}
        <span style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)' }}>
          {formatLine(item)}
        </span>
      </div>
      <span style={{ color: 'var(--color-text-dim)', flexShrink: 0, fontFamily: 'var(--font-mono)', fontSize: 10 }}>
        {timeAgo(item.created_at)}
      </span>
    </div>
  )
}
