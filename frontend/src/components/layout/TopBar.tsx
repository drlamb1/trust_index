import { useState, useEffect } from 'react'
import { Search, Bell } from 'lucide-react'

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

export default function TopBar() {
  return (
    <header
      className="fixed top-0 right-0 flex items-center justify-between px-6"
      style={{
        left: 72,
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
        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
          style={{
            background: 'hsl(228 18% 11%)',
            border: '1px solid var(--color-border)',
            width: 200,
          }}
        >
          <Search size={13} style={{ color: 'var(--color-text-dim)' }} />
          <span style={{ color: 'var(--color-text-dim)', fontSize: 12, fontFamily: 'var(--font-sans)' }}>
            Search tickers, theses…
          </span>
        </div>
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
