import { useState, useEffect, useRef } from 'react'
import { Search, Menu } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { tickers } from '@/lib/api'

function Clock({ compact }: { compact?: boolean }) {
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])

  const fmt = compact
    ? time.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : time.toLocaleString('en-US', {
        weekday: 'short', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
      })

  // Market hours in ET (Mon-Fri 9:30-16:00)
  const et = new Date(time.toLocaleString('en-US', { timeZone: 'America/New_York' }))
  const etDay = et.getDay()
  const etMinutes = et.getHours() * 60 + et.getMinutes()
  const marketOpen = etDay >= 1 && etDay <= 5 && etMinutes >= 570 && etMinutes < 960

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
        {marketOpen ? 'Open' : 'Closed'}
      </span>
    </div>
  )
}

function TickerSearch({ compact }: { compact?: boolean }) {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const [selectedIdx, setSelectedIdx] = useState(-1)
  const navigate = useNavigate()
  const blurTimeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: tickerList = [] } = useQuery({
    queryKey: ['ticker-list'],
    queryFn: tickers.list,
    staleTime: 60 * 60_000,
    enabled: focused,
  })

  const query = value.trim().toUpperCase()
  const matches = query.length > 0
    ? tickerList
        .filter(t =>
          t.symbol.startsWith(query) ||
          (t.name && t.name.toLowerCase().includes(value.trim().toLowerCase()))
        )
        .slice(0, 8)
    : []

  const showDropdown = focused && matches.length > 0

  const selectTicker = (symbol: string) => {
    navigate(`/tickers/${symbol}`)
    setValue('')
    setSelectedIdx(-1)
    inputRef.current?.blur()
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (selectedIdx >= 0 && matches[selectedIdx]) {
      selectTicker(matches[selectedIdx].symbol)
    } else if (query) {
      selectTicker(query)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showDropdown) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIdx(prev => Math.min(prev + 1, matches.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIdx(prev => Math.max(prev - 1, -1))
    } else if (e.key === 'Escape') {
      inputRef.current?.blur()
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ position: 'relative' }}>
      <div
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
        style={{
          background: 'hsl(228 18% 11%)',
          border: `1px solid ${focused ? 'var(--color-amber-dim)' : 'var(--color-border)'}`,
          width: compact ? 140 : 200,
          transition: 'border-color 0.15s',
        }}
      >
        <Search size={13} style={{ color: 'var(--color-text-dim)', flexShrink: 0 }} />
        <input
          ref={inputRef}
          value={value}
          onChange={e => { setValue(e.target.value); setSelectedIdx(-1) }}
          onFocus={() => { setFocused(true); clearTimeout(blurTimeout.current) }}
          onBlur={() => { blurTimeout.current = setTimeout(() => setFocused(false), 150) }}
          onKeyDown={handleKeyDown}
          placeholder={compact ? 'Search…' : 'Search tickers…'}
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

      {showDropdown && (
        <div
          style={{
            position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4,
            background: 'hsl(228 18% 11%)',
            border: '1px solid var(--color-border)',
            borderRadius: 8, overflow: 'hidden', zIndex: 50,
            boxShadow: '0 8px 24px hsl(228 25% 4% / 0.6)',
          }}
        >
          {matches.map((t, i) => (
            <div
              key={t.symbol}
              onMouseDown={() => selectTicker(t.symbol)}
              onMouseEnter={() => setSelectedIdx(i)}
              className="flex items-center gap-2 px-3 py-2"
              style={{
                cursor: 'pointer',
                background: i === selectedIdx ? 'hsl(228 15% 16%)' : 'transparent',
              }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600, color: 'var(--color-amber)', minWidth: 48 }}>
                {t.symbol}
              </span>
              {t.name && (
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {t.name}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </form>
  )
}

export default function TopBar({ isMobile, onMenuToggle }: { isMobile?: boolean; onMenuToggle?: () => void }) {
  return (
    <header
      className="fixed top-0 right-0 flex items-center justify-between px-4 md:px-6"
      style={{
        left: isMobile ? 0 : 88,
        height: 56,
        background: 'hsl(228 22% 7% / 0.8)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--color-border)',
        zIndex: 40,
      }}
    >
      {/* Left — hamburger (mobile) or logo (desktop) */}
      <div className="flex items-center gap-3">
        {isMobile && onMenuToggle && (
          <button
            onClick={onMenuToggle}
            style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', padding: 4 }}
          >
            <Menu size={20} />
          </button>
        )}
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: isMobile ? 16 : 18, fontWeight: 600, letterSpacing: '-0.01em' }}>
          <span style={{ color: 'var(--color-text-primary)' }}>Edge</span>
          <span style={{ color: 'var(--color-amber)' }}>Finder</span>
        </div>
      </div>

      {/* Center — clock (hidden on very small screens, compact on mobile) */}
      {!isMobile && <Clock />}
      {isMobile && <Clock compact />}

      {/* Right — search */}
      <div className="flex items-center gap-3">
        <TickerSearch compact={isMobile} />
      </div>
    </header>
  )
}
