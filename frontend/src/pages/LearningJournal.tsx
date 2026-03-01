// Learning Journal — institutional memory
// Agent memories as cards, post-mortems, searchable

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { simulation } from '@/lib/api'
import { agentColor, CHAT_PERSONAS, PERSONAS } from '@/lib/personas'
import type { AgentMemory } from '@/types/api'

const MEMORY_BORDER: Record<string, string> = {
  insight: 'var(--color-amber)',
  pattern: 'var(--color-cyan)',
  failure: 'var(--color-danger)',
  success: 'var(--color-success)',
  lesson_taught: 'hsl(260 60% 65%)',
}

const MEMORY_ICON: Record<string, string> = {
  insight: '💡',
  pattern: '🔄',
  failure: '⚠️',
  success: '✅',
  lesson_taught: '🎓',
}

function MemoryCard({ memory }: { memory: AgentMemory }) {
  const border = MEMORY_BORDER[memory.memory_type] ?? 'var(--color-border)'
  return (
    <div
      style={{
        background: 'hsl(228 18% 10%)',
        border: `1px solid var(--color-border)`,
        borderLeft: `3px solid ${border}`,
        borderRadius: '0 8px 8px 0',
        padding: '14px 16px',
        marginBottom: 8,
      }}
    >
      <div className="flex items-center gap-2" style={{ marginBottom: 6 }}>
        <span style={{ fontSize: 13 }}>{MEMORY_ICON[memory.memory_type] ?? '📝'}</span>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: border }}>
          {memory.memory_type}
        </span>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-dim)' }}>
          {Math.round(memory.confidence * 100)}% confidence
        </span>
      </div>
      <div style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--color-text-primary)', lineHeight: 1.6, marginBottom: 6 }}>
        {memory.content}
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: 10, color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)' }}>
        <span style={{ color: agentColor(memory.agent_name) }}>{memory.agent_name}</span>
        <span>accessed {memory.access_count}×</span>
      </div>
    </div>
  )
}

export default function LearningJournal() {
  const [filter, setFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [agentFilter, setAgentFilter] = useState<string>('')
  const [limit, setLimit] = useState(30)

  const { data: memories = [] } = useQuery({
    queryKey: ['memories', agentFilter, typeFilter, limit],
    queryFn: () => simulation.memories({
      agent_name: agentFilter || undefined,
      memory_type: typeFilter || undefined,
      limit,
    }),
    refetchInterval: 60_000,
  })

  const filtered = filter
    ? memories.filter(m => m.content.toLowerCase().includes(filter.toLowerCase()))
    : memories

  return (
    <div>
      <h1 style={{ fontFamily: 'var(--font-sans)', fontSize: 18, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>
        Learning Journal
      </h1>
      <div style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 20 }}>
        The scar tissue. Durable lessons extracted from every thesis — what worked, what failed, and why.
      </div>

      {/* Filters */}
      <div className="flex gap-3" style={{ marginBottom: 20 }}>
        <div className="glass-sm flex items-center gap-2 flex-1" style={{ padding: '8px 12px' }}>
          <Search size={13} style={{ color: 'var(--color-text-dim)' }} />
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Search memories…"
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--color-text-primary)',
            }}
          />
        </div>

        {['', 'insight', 'pattern', 'failure', 'success', 'lesson_taught'].map(t => (
          <button
            key={t}
            onClick={() => setTypeFilter(t)}
            className="pill"
            style={{
              cursor: 'pointer',
              background: typeFilter === t ? (MEMORY_BORDER[t] ?? 'var(--color-amber)') + '20' : 'hsl(228 18% 11%)',
              color: typeFilter === t ? (MEMORY_BORDER[t] ?? 'var(--color-amber)') : 'var(--color-text-muted)',
              border: `1px solid ${typeFilter === t ? (MEMORY_BORDER[t] ?? 'var(--color-amber)') + '60' : 'var(--color-border)'}`,
            }}
          >
            {t === '' ? 'All' : t === 'lesson_taught' ? 'lessons' : t}
          </button>
        ))}
      </div>

      {/* Agent filter pills */}
      <div className="flex gap-1.5 flex-wrap" style={{ marginBottom: 16 }}>
        <button
          onClick={() => setAgentFilter('')}
          className="pill"
          style={{
            cursor: 'pointer', fontSize: 10,
            background: agentFilter === '' ? 'var(--color-amber-muted)' : 'hsl(228 18% 11%)',
            color: agentFilter === '' ? 'var(--color-amber)' : 'var(--color-text-dim)',
            border: `1px solid ${agentFilter === '' ? 'var(--color-amber-dim)' : 'var(--color-border)'}`,
          }}
        >
          All agents
        </button>
        {CHAT_PERSONAS.map(name => {
          const p = PERSONAS[name]
          const isActive = agentFilter === name
          return (
            <button
              key={name}
              onClick={() => setAgentFilter(name)}
              className="pill"
              style={{
                cursor: 'pointer', fontSize: 10,
                background: isActive ? p.color + '20' : 'hsl(228 18% 11%)',
                color: isActive ? p.color : 'var(--color-text-dim)',
                border: `1px solid ${isActive ? p.color + '60' : 'var(--color-border)'}`,
              }}
            >
              <span style={{ marginRight: 3 }}>{p.icon}</span>
              {p.display_name}
            </button>
          )
        })}
      </div>

      {/* Memory cards */}
      {filtered.length === 0 && (
        <div style={{ color: 'var(--color-text-dim)', fontSize: 12, fontFamily: 'var(--font-sans)', padding: '40px 0', textAlign: 'center' }}>
          No memories yet. The Post-Mortem Priest consolidates lessons weekly from simulation activity.
        </div>
      )}
      {filtered.map(m => <MemoryCard key={m.id} memory={m} />)}

      {memories.length >= limit && (
        <button
          onClick={() => setLimit(l => l + 30)}
          style={{
            background: 'transparent', border: '1px solid var(--color-border)',
            borderRadius: 6, padding: '6px 16px', cursor: 'pointer',
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--color-text-dim)', marginTop: 12,
            display: 'block', width: '100%',
          }}
        >
          Load more
        </button>
      )}
    </div>
  )
}
