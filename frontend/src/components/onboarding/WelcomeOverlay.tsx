// WelcomeOverlay — shown once on first visit, never again
// Stored in localStorage as ef_onboarding_done

import { useNavigate } from 'react-router-dom'
import { MessageSquare, Zap, BookOpenCheck } from 'lucide-react'

const EDGE_COLOR = '#ff4f81'

interface Props {
  onDismiss: () => void
}

export default function WelcomeOverlay({ onDismiss }: Props) {
  const navigate = useNavigate()

  const actions = [
    {
      icon: MessageSquare,
      label: 'Chat with The Edger',
      desc: 'Tell me what you\'re curious about. I\'ll handle the rest.',
      color: EDGE_COLOR,
      onClick: () => {
        onDismiss()
        navigate('/chat?persona=edge')
      },
    },
    {
      icon: Zap,
      label: 'Explore the Dashboard',
      desc: 'Dive right in. Click the glowing dots.',
      color: 'var(--color-amber)',
      onClick: onDismiss,
    },
    {
      icon: BookOpenCheck,
      label: 'Read the Guide',
      desc: 'Meet all 9 personas and see what they do.',
      color: 'var(--color-cyan)',
      onClick: () => {
        onDismiss()
        navigate('/guide')
      },
    },
  ]

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 200,
        background: 'hsl(228 25% 6% / 0.92)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onDismiss() }}
    >
      <div
        className="glass animate-entry"
        style={{
          maxWidth: 520, width: '100%', padding: '32px 32px 24px',
        }}
      >
        {/* Badge */}
        <div className="flex items-center gap-2" style={{ marginBottom: 20 }}>
          <span style={{
            fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12,
            color: EDGE_COLOR, background: EDGE_COLOR + '18',
            border: `1px solid ${EDGE_COLOR}40`, borderRadius: 6,
            padding: '2px 8px',
          }}>
            E
          </span>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: EDGE_COLOR, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            The Edger
          </span>
        </div>

        {/* Welcome text */}
        <h1 style={{ fontFamily: 'var(--font-sans)', fontSize: 20, fontWeight: 700, color: 'var(--color-text-primary)', marginBottom: 12 }}>
          Welcome to EdgeFinder
        </h1>
        <p style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--color-text-muted)', lineHeight: 1.7, marginBottom: 24 }}>
          You've got 9 AI agents who live here. They analyze markets, build theses, test them
          with simulated money, and learn from their mistakes. I'm The Edger — your front door.
          Where do you want to start?
        </p>

        {/* Action cards */}
        <div className="flex flex-col gap-2" style={{ marginBottom: 20 }}>
          {actions.map(({ icon: Icon, label, desc, color, onClick }) => (
            <button
              key={label}
              onClick={onClick}
              className="flex items-start gap-3"
              style={{
                background: 'hsl(228 15% 14%)',
                border: '1px solid var(--color-border)',
                borderRadius: 8, padding: '12px 16px',
                cursor: 'pointer', width: '100%', textAlign: 'left',
                transition: 'border-color 0.15s',
              }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = typeof color === 'string' && color.startsWith('#') ? color + '60' : 'var(--color-amber-dim)')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--color-border)')}
            >
              <div
                className="flex items-center justify-center rounded-lg flex-shrink-0"
                style={{
                  width: 32, height: 32,
                  background: typeof color === 'string' && color.startsWith('#') ? color + '18' : 'var(--color-amber-muted)',
                  border: `1px solid ${typeof color === 'string' && color.startsWith('#') ? color + '40' : 'var(--color-amber-dim)'}`,
                }}
              >
                <Icon size={14} style={{ color: typeof color === 'string' && color.startsWith('#') ? color : 'var(--color-amber)' }} />
              </div>
              <div>
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 2 }}>
                  {label}
                </div>
                <div style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-dim)' }}>
                  {desc}
                </div>
              </div>
            </button>
          ))}
        </div>

        {/* Dismiss */}
        <button
          onClick={onDismiss}
          style={{
            background: 'transparent', border: 'none',
            color: 'var(--color-text-dim)', cursor: 'pointer',
            fontFamily: 'var(--font-sans)', fontSize: 11,
            width: '100%', textAlign: 'center', padding: '6px 0',
          }}
        >
          Skip — I'll figure it out
        </button>
      </div>
    </div>
  )
}
