// Intelligence Feed — SSE-driven narrative alerts
// Icon encoding type, ticker badge, one-line story, timestamp

import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Zap, AlertTriangle, FileSearch, BarChart2, TrendingDown, Info } from 'lucide-react'
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

function typeIcon(eventType: string) {
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

export default function IntelligenceFeed() {
  const navigate = useNavigate()
  const [items, setItems] = useState<FeedItem[]>([])
  const [connected, setConnected] = useState(false)
  const [timedOut, setTimedOut] = useState(false)
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
          to="/journal"
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
        {items.map((item, i) => {
          const Icon = typeIcon(item.event_type)
          const ticker = item.event_data?.ticker as string | undefined
          return (
            <div
              key={`${item.id}-${i}`}
              className="flex items-start gap-2"
              onClick={() => ticker && navigate(`/tickers/${ticker}`)}
              style={{
                padding: '6px 0', borderBottom: '1px solid var(--color-border)', fontSize: 11,
                cursor: ticker ? 'pointer' : 'default',
              }}
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
        })}
      </div>
    </div>
  )
}
