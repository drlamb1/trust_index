// Agent Console — quick-access chat gateway
// Persona tabs + input → navigates to /chat with persona pre-selected

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Send, User } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { PERSONAS } from '@/lib/personas'
import type { PersonaName } from '@/types/api'

const QUICK_PERSONAS: PersonaName[] = ['analyst', 'thesis', 'pm']

export default function AgentConsole() {
  const navigate = useNavigate()
  const { activePersona, setPersona } = useAuthStore()
  const [message, setMessage] = useState('')

  const selectedPersona = QUICK_PERSONAS.includes(activePersona) ? activePersona : 'analyst'

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!message.trim()) return
    navigate(`/chat?message=${encodeURIComponent(message)}&persona=${selectedPersona}`)
    setMessage('')
  }

  return (
    <div className="glass animate-entry animate-entry-5" style={{ padding: '20px 24px' }}>
      <h2 style={{
        fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600,
        letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--color-text-muted)',
        marginBottom: 12,
      }}>
        Agent Console
      </h2>

      {/* Persona tabs */}
      <div className="flex gap-2" style={{ marginBottom: 12 }}>
        {QUICK_PERSONAS.map(pName => {
          const p = PERSONAS[pName]
          const isActive = selectedPersona === pName
          return (
            <button
              key={pName}
              onClick={() => setPersona(pName)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors"
              style={{
                fontFamily: 'var(--font-sans)',
                fontSize: 11,
                fontWeight: 500,
                border: `1px solid ${isActive ? p.color + '60' : 'var(--color-border)'}`,
                background: isActive ? p.color + '18' : 'transparent',
                color: isActive ? p.color : 'var(--color-text-muted)',
                cursor: 'pointer',
              }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 10 }}>
                {p.icon}
              </span>
              {p.display_name}
            </button>
          )
        })}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={message}
          onChange={e => setMessage(e.target.value)}
          placeholder="Ask the agents anything…"
          className="flex-1 px-3 py-2 rounded-lg"
          style={{
            background: 'hsl(228 15% 14%)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            fontSize: 12,
            outline: 'none',
          }}
          onFocus={e => (e.target.style.borderColor = 'var(--color-amber)')}
          onBlur={e => (e.target.style.borderColor = 'var(--color-border)')}
        />
        <button
          type="submit"
          disabled={!message.trim()}
          className="flex items-center justify-center rounded-lg transition-colors"
          style={{
            width: 36, height: 36, flexShrink: 0,
            background: message.trim() ? 'var(--color-amber)' : 'var(--color-amber-muted)',
            border: 'none', cursor: message.trim() ? 'pointer' : 'not-allowed',
          }}
        >
          <Send size={14} style={{ color: message.trim() ? '#000' : 'var(--color-amber-dim)' }} />
        </button>
      </form>

      <div style={{ marginTop: 8, fontSize: 10, color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)' }}>
        All 8 personas available in full chat →
      </div>
    </div>
  )
}
