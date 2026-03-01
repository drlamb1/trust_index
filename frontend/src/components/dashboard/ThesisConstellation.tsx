// Thesis Constellation — force-directed graph
// Nodes = simulated theses, size ∝ conviction, color = category
// Edges = signal correlation
// Click node → emit onThesisSelect

import { useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import ForceGraph2D from 'react-force-graph-2d'
import { simulation } from '@/lib/api'
import type { SimulatedThesis } from '@/types/api'

// Category → color mapping
const CATEGORY_COLORS: Record<string, string> = {
  momentum: 'hsl(38 92% 55%)',    // amber
  value:    'hsl(185 72% 48%)',   // cyan
  event:    'hsl(142 71% 45%)',   // green
  macro:    'hsl(270 60% 65%)',   // purple
  default:  'hsl(220 10% 50%)',   // muted
}

function inferCategory(thesis: SimulatedThesis): string {
  const text = (thesis.name + ' ' + thesis.thesis_text).toLowerCase()
  if (text.includes('momentum') || text.includes('breakout') || text.includes('trend')) return 'momentum'
  if (text.includes('value') || text.includes('pe ') || text.includes('undervalued')) return 'value'
  if (text.includes('earnings') || text.includes('event') || text.includes('catalyst')) return 'event'
  if (text.includes('macro') || text.includes('fed') || text.includes('rate') || text.includes('inflation')) return 'macro'
  return 'default'
}

function convictionRadius(thesis: SimulatedThesis): number {
  if (thesis.status === 'paper_live') return 10
  if (thesis.status === 'backtesting') return 8
  if (thesis.status === 'proposed') return 6
  return 5
}

interface Props {
  onThesisSelect?: (thesis: SimulatedThesis) => void
  height?: number
}

export default function ThesisConstellation({ onThesisSelect, height = 400 }: Props) {
  const { data: theses = [], isError } = useQuery({
    queryKey: ['theses-all'],
    queryFn: () => simulation.theses(),
    refetchInterval: 30_000,
  })

  const graphRef = useRef<any>(null)

  // Build graph data from theses
  const graphData = useCallback(() => {
    if (!theses.length) return { nodes: [], links: [] }

    const nodes = theses.map(t => ({
      id: String(t.id),
      thesis: t,
      label: t.name.length > 20 ? t.name.slice(0, 18) + '…' : t.name,
      color: CATEGORY_COLORS[inferCategory(t)],
      radius: convictionRadius(t),
    }))

    // Create edges between theses that share ticker_ids
    const links: Array<{ source: string; target: string }> = []
    for (let i = 0; i < theses.length; i++) {
      for (let j = i + 1; j < theses.length; j++) {
        const a = theses[i].ticker_ids ?? []
        const b = theses[j].ticker_ids ?? []
        const overlap = a.filter(id => b.includes(id))
        if (overlap.length > 0) {
          links.push({ source: String(theses[i].id), target: String(theses[j].id) })
        }
      }
    }

    return { nodes, links }
  }, [theses])

  const data = graphData()

  // Empty / error state
  if (!theses.length || isError) {
    return (
      <div
        className="glass animate-entry"
        style={{ padding: '24px', height }}
      >
        <div style={{
          fontFamily: 'var(--font-sans)',
          fontSize: 11, fontWeight: 600, letterSpacing: '0.1em',
          textTransform: 'uppercase', color: 'var(--color-text-muted)',
          marginBottom: 8,
        }}>
          Thesis Constellation
        </div>
        <div style={{ color: 'var(--color-text-dim)', fontSize: 11 }}>
          Signal correlations · confidence-weighted
        </div>
        <div
          className="flex items-center justify-center"
          style={{ height: height - 80, color: isError ? 'var(--color-danger)' : 'var(--color-text-dim)', fontSize: 12, textAlign: 'center', lineHeight: 1.6 }}
        >
          {isError ? 'Failed to load theses — backend may be starting up.' : <>No theses yet.<br />Ask the Thesis Lord to generate one.</>}
        </div>
      </div>
    )
  }

  const STATUS_COLOR: Record<string, string> = {
    proposed: 'var(--color-text-muted)',
    backtesting: 'var(--color-amber)',
    paper_live: 'var(--color-success)',
    retired: 'var(--color-text-dim)',
    killed: 'var(--color-danger)',
  }

  // Canvas gets less height to make room for the clickable list
  const canvasHeight = Math.max(height - 180, 120)

  return (
    <div className="glass animate-entry" style={{ padding: '20px 24px', height, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div className="flex items-center justify-between" style={{ marginBottom: 4, flexShrink: 0 }}>
        <h2 style={{
          fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600,
          letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--color-text-muted)',
        }}>
          Thesis Constellation
        </h2>
      </div>
      <div style={{ color: 'var(--color-text-dim)', fontSize: 11, marginBottom: 8, flexShrink: 0 }}>
        Signal correlations · confidence-weighted
      </div>

      {/* Force graph */}
      <div className="constellation-canvas" style={{ borderRadius: 8, overflow: 'hidden', flexShrink: 0 }}>
        <ForceGraph2D
          ref={graphRef}
          graphData={data}
          width={undefined}
          height={canvasHeight}
          backgroundColor="transparent"
          nodeRelSize={1}
          nodeVal={node => (node as any).radius ** 2}
          nodeColor={node => (node as any).color}
          nodeLabel={node => (node as any).label}
          linkColor={() => 'rgba(255,255,255,0.06)'}
          linkWidth={1}
          onNodeClick={(node: any) => {
            if (node.thesis) onThesisSelect?.(node.thesis)
          }}
          onNodeHover={(node: any) => {
            const el = graphRef.current?.['_canvas'] as HTMLCanvasElement | undefined
            if (el) el.style.cursor = node ? 'pointer' : 'default'
          }}
          nodeCanvasObject={(node: any, ctx, globalScale) => {
            const r = node.radius
            const color = node.color

            // Outer glow for live theses
            if (node.thesis?.status === 'paper_live') {
              ctx.beginPath()
              ctx.arc(node.x, node.y, r + 4, 0, 2 * Math.PI)
              ctx.fillStyle = color.replace(')', ' / 0.15)')
              ctx.fill()
            }

            // Main node
            ctx.beginPath()
            ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
            ctx.fillStyle = color
            ctx.fill()

            // Label (show at reasonable zoom levels)
            if (globalScale > 0.7) {
              ctx.font = `${10 / globalScale}px "Space Grotesk", sans-serif`
              ctx.fillStyle = 'rgba(255,255,255,0.7)'
              ctx.textAlign = 'center'
              ctx.textBaseline = 'top'
              ctx.fillText(node.label, node.x, node.y + r + 2)
            }
          }}
          cooldownTicks={100}
          onEngineStop={() => graphRef.current?.zoomToFit(400, 40)}
        />
      </div>

      {/* Legend */}
      <div className="flex gap-4" style={{ marginTop: 6, flexShrink: 0 }}>
        {Object.entries(CATEGORY_COLORS).filter(([k]) => k !== 'default').map(([key, color]) => (
          <div key={key} className="flex items-center gap-1.5" style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
            <span style={{ textTransform: 'capitalize', fontFamily: 'var(--font-sans)' }}>{key}</span>
          </div>
        ))}
      </div>

      {/* Clickable thesis list — DOM fallback for canvas nodes */}
      <div style={{ marginTop: 8, flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {theses.map(t => {
          const color = CATEGORY_COLORS[inferCategory(t)]
          const statusColor = STATUS_COLOR[t.status] ?? 'var(--color-text-muted)'
          return (
            <button
              key={t.id}
              onClick={() => onThesisSelect?.(t)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                width: '100%', padding: '4px 6px', marginBottom: 2,
                background: 'transparent', border: 'none', borderRadius: 4,
                cursor: 'pointer', textAlign: 'left',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'hsl(228 15% 14%)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-primary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {t.name}
              </span>
              {t.ticker_symbol && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--color-amber)', flexShrink: 0 }}>
                  {t.ticker_symbol}
                </span>
              )}
              <span className="pill" style={{
                fontSize: 8, flexShrink: 0, padding: '1px 5px',
                background: statusColor + '20', color: statusColor,
                border: `1px solid ${statusColor}40`,
              }}>
                {t.status.replace('_', ' ')}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
