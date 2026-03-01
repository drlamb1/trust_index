import { useState, useEffect } from 'react'
import { Search, Bell } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

function Clock() {
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])

  const fmt = time.toLocaleString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
  })

  // Simple market hours check (ET Mon-Fri 9:30-16:00)
  const day = time.getDay()
  const hours = time.getUTCHours() * 60 + time.getUTCMinutes()
  const marketOpen = day >= 1 && day <= 5 && hours >= 870 && hours < 1200 // 14:30-20:00 UTC

  return (
    <div className="flex items-center gap-2" style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
      <span>{fmt}</span>
      <span
        className="pill"
        style={{
          background: marketOpen ? 'hsl(142 40% 12%)' : 'hsl(228 15% 14%)',
          color: marketOpen ? 'var(--color-success)' : 'var(--color-text-dim)',
          border: `1px solid ${marketOpen ? 'hsl(142 40% 25%)' : 'var(--color-border)'}`,
        }}
      >
        {marketOpen ? 'Markets Open' : 'Markets Closed'}
      </span>
    </div>
  )
}

function TickerSearch() {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const sym = value.trim().toUpperCase()
    if (sym) {
      navigate(`/tickers/${sym}`)
      setValue('')
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
        style={{
          background: 'hsl(228 18% 11%)',
          border: `1px solid ${focused ? 'var(--color-amber-dim)' : 'var(--color-border)'}`,
          width: 200,
          transition: 'border-color 0.15s',
        }}
      >
        <Search size={13} style={{ color: 'var(--color-text-dim)', flexShrink: 0 }} />
        <input
          value={value}
          onChange={e => setValue(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="Search tickers…"
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: 'var(--color-text-primary)',
          }}
        />
      </div>
    </form>
  )
}

export default function TopBar() {
  return (
    <header
      className="fixed top-0 right-0 flex items-center justify-between px-6"
      style={{
        left: 88,
        height: 56,
        background: 'hsl(228 22% 7% / 0.8)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--color-border)',
        zIndex: 40,
      }}
    >
      {/* Logo text */}
      <div style={{ fontFamily: 'var(--font-sans)', fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>
        <span style={{ color: 'var(--color-text-primary)' }}>Edge</span>
        <span style={{ color: 'var(--color-amber)' }}>Finder</span>
      </div>

      {/* Center — clock */}
      <Clock />

      {/* Right — search + bell */}
      <div className="flex items-center gap-3">
        <TickerSearch />
        <button
          className="flex items-center justify-center w-8 h-8 rounded-lg transition-colors"
          style={{ color: 'var(--color-text-dim)', border: '1px solid var(--color-border)', background: 'transparent' }}
        >
          <Bell size={14} />
        </button>
      </div>
    </header>
  )
}
