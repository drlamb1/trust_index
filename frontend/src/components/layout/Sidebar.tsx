import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  FlaskConical,
  MessageSquare,
  BookOpen,
  FileText,
  Settings,
  BookOpenCheck,
  Zap,
  X,
} from 'lucide-react'
import { useEffect } from 'react'

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/simulation', icon: FlaskConical, label: 'Simulation Lab' },
  { to: '/chat', icon: MessageSquare, label: 'Agent Chat' },
  { to: '/journal', icon: BookOpen, label: 'Learning Journal' },
  { to: '/briefing', icon: FileText, label: 'Briefing' },
]

const labelStyle = {
  fontFamily: 'var(--font-sans)', fontSize: 8, fontWeight: 600,
  letterSpacing: '0.02em', textAlign: 'center' as const, lineHeight: 1.2,
}

function NavItem({ to, icon: Icon, label, onClick }: { to: string; icon: typeof LayoutDashboard; label: string; onClick?: () => void }) {
  return (
    <NavLink
      key={to}
      to={to}
      end={to === '/'}
      title={label}
      onClick={onClick}
      className={({ isActive }) =>
        `flex flex-col items-center justify-center gap-1 py-2 px-1 rounded-lg transition-colors ${
          isActive ? 'text-amber bg-amber-muted' : 'text-dim hover:text-muted'
        }`
      }
      style={({ isActive }) => ({
        color: isActive ? 'var(--color-amber)' : 'var(--color-text-dim)',
        background: isActive ? 'var(--color-amber-muted)' : 'transparent',
      })}
    >
      <Icon size={16} />
      <span style={labelStyle}>{label}</span>
    </NavLink>
  )
}

/* ── Desktop sidebar (fixed rail) ── */
export function DesktopSidebar() {
  return (
    <nav
      className="fixed left-0 top-0 h-screen flex-col items-center py-4 z-50 hidden md:flex"
      style={{ width: 88, background: 'hsl(228 22% 7%)', borderRight: '1px solid var(--color-border)' }}
    >
      {/* Logo */}
      <div className="mb-8 flex items-center justify-center w-10 h-10 rounded-xl"
           style={{ background: 'var(--color-amber-muted)', border: '1px solid var(--color-amber-dim)' }}>
        <Zap size={18} style={{ color: 'var(--color-amber)' }} />
      </div>

      {/* Nav items */}
      <div className="flex flex-col gap-1 flex-1">
        {NAV.map(({ to, icon, label }) => (
          <NavItem key={to} to={to} icon={icon} label={label} />
        ))}
      </div>

      {/* Bottom group */}
      <div className="flex flex-col gap-1 items-center">
        <NavItem to="/guide" icon={BookOpenCheck} label="Guide" />
        <NavItem to="/settings" icon={Settings} label="Settings" />
      </div>
    </nav>
  )
}

/* ── Mobile drawer (slide-over) ── */
export function MobileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const location = useLocation()

  // Close drawer on navigation
  useEffect(() => { onClose() }, [location.pathname]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, zIndex: 90,
          background: 'hsl(228 25% 4% / 0.7)',
          backdropFilter: 'blur(4px)',
        }}
      />

      {/* Drawer */}
      <nav
        className="flex flex-col py-4 z-100"
        style={{
          position: 'fixed', left: 0, top: 0, bottom: 0, width: 220, zIndex: 100,
          background: 'hsl(228 22% 7%)',
          borderRight: '1px solid var(--color-border)',
          boxShadow: '4px 0 24px hsl(228 25% 4% / 0.6)',
        }}
      >
        {/* Header with logo + close */}
        <div className="flex items-center justify-between px-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl"
                 style={{ background: 'var(--color-amber-muted)', border: '1px solid var(--color-amber-dim)' }}>
              <Zap size={18} style={{ color: 'var(--color-amber)' }} />
            </div>
            <div style={{ fontFamily: 'var(--font-sans)', fontSize: 16, fontWeight: 600 }}>
              <span style={{ color: 'var(--color-text-primary)' }}>Edge</span>
              <span style={{ color: 'var(--color-amber)' }}>Finder</span>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', padding: 4 }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Nav items — horizontal layout with labels */}
        <div className="flex flex-col gap-1 flex-1 px-2">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 py-2.5 px-3 rounded-lg transition-colors ${
                  isActive ? '' : 'hover:bg-white/5'
                }`
              }
              style={({ isActive }) => ({
                color: isActive ? 'var(--color-amber)' : 'var(--color-text-muted)',
                background: isActive ? 'var(--color-amber-muted)' : 'transparent',
              })}
            >
              <Icon size={16} />
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 500 }}>
                {label}
              </span>
            </NavLink>
          ))}
        </div>

        {/* Bottom group */}
        <div className="flex flex-col gap-1 px-2">
          {[
            { to: '/guide', icon: BookOpenCheck, label: 'Guide' },
            { to: '/settings', icon: Settings, label: 'Settings' },
          ].map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              className="flex items-center gap-3 py-2.5 px-3 rounded-lg transition-colors hover:bg-white/5"
              style={({ isActive }) => ({
                color: isActive ? 'var(--color-amber)' : 'var(--color-text-dim)',
                background: isActive ? 'var(--color-amber-muted)' : 'transparent',
              })}
            >
              <Icon size={16} />
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 500 }}>
                {label}
              </span>
            </NavLink>
          ))}
        </div>
      </nav>
    </>
  )
}

// Default export for backward compat (desktop only)
export default function Sidebar() {
  return <DesktopSidebar />
}
