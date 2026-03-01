// Agent Console — The Edger is the front door
// Single input → always routes to Edge persona in /chat

import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Send } from 'lucide-react'

const EDGE_COLOR = '#ff4f81'

export default function AgentConsole() {
  const navigate = useNavigate()
  const [message, setMessage] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!message.trim()) return
    navigate(`/chat?message=${encodeURIComponent(message)}&persona=edge`)
    setMessage('')
  }

  return (
    <div className="glass animate-entry animate-entry-5" style={{ padding: '20px 24px' }}>
      {/* Edger branding */}
      <div className="flex items-center gap-2" style={{ marginBottom: 12 }}>
        <span style={{
          fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 11,
          color: EDGE_COLOR, background: EDGE_COLOR + '18',
          border: `1px solid ${EDGE_COLOR}40`, borderRadius: 6,
          padding: '2px 7px',
        }}>
          E
        </span>
        <h2 style={{
          fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600,
          letterSpacing: '0.1em', textTransform: 'uppercase', color: EDGE_COLOR,
          margin: 0,
        }}>
          The Edger
        </h2>
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={message}
          onChange={e => setMessage(e.target.value)}
          placeholder="What's on your mind? I'll handle the rest."
          className="flex-1 px-3 py-2 rounded-lg"
          style={{
            background: 'hsl(228 15% 14%)',
            border: `1px solid ${EDGE_COLOR}30`,
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-sans)',
            fontSize: 12,
            outline: 'none',
          }}
          onFocus={e => (e.target.style.borderColor = EDGE_COLOR)}
          onBlur={e => (e.target.style.borderColor = EDGE_COLOR + '30')}
        />
        <button
          type="submit"
          disabled={!message.trim()}
          className="flex items-center justify-center rounded-lg transition-colors"
          style={{
            width: 36, height: 36, flexShrink: 0,
            background: message.trim() ? EDGE_COLOR : EDGE_COLOR + '30',
            border: 'none', cursor: message.trim() ? 'pointer' : 'not-allowed',
          }}
        >
          <Send size={14} style={{ color: message.trim() ? '#fff' : EDGE_COLOR + '60' }} />
        </button>
      </form>

      <Link
        to="/chat"
        style={{
          display: 'block', marginTop: 8, fontSize: 10,
          color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)',
          textDecoration: 'none',
        }}
      >
        All 9 personas available in full chat →
      </Link>
    </div>
  )
}
