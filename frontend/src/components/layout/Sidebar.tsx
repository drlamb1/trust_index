import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  FlaskConical,
  MessageSquare,
  BookOpen,
  FileText,
  Settings,
  Zap,
} from 'lucide-react'

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/simulation', icon: FlaskConical, label: 'Simulation Lab' },
  { to: '/chat', icon: MessageSquare, label: 'Agent Chat' },
  { to: '/journal', icon: BookOpen, label: 'Learning Journal' },
  { to: '/briefing', icon: FileText, label: 'Briefing' },
]

export default function Sidebar() {
  return (
    <nav
      className="fixed left-0 top-0 h-screen flex flex-col items-center py-4 z-50"
      style={{ width: 72, background: 'hsl(228 22% 7%)', borderRight: '1px solid var(--color-border)' }}
    >
      {/* Logo */}
      <div className="mb-8 flex items-center justify-center w-10 h-10 rounded-xl"
           style={{ background: 'var(--color-amber-muted)', border: '1px solid var(--color-amber-dim)' }}>
        <Zap size={18} style={{ color: 'var(--color-amber)' }} />
      </div>

      {/* Nav items */}
      <div className="flex flex-col gap-1 flex-1">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            title={label}
            className={({ isActive }) =>
              `group relative flex items-center justify-center w-10 h-10 rounded-lg transition-colors ${
                isActive
                  ? 'text-amber bg-amber-muted'
                  : 'text-dim hover:text-muted'
              }`
            }
            style={({ isActive }) => ({
              color: isActive ? 'var(--color-amber)' : 'var(--color-text-dim)',
              background: isActive ? 'var(--color-amber-muted)' : 'transparent',
            })}
          >
            <Icon size={16} />
            {/* Tooltip */}
            <span
              className="absolute left-14 px-2 py-1 rounded text-xs pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-50"
              style={{
                background: 'hsl(228 20% 14%)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-primary)',
                fontFamily: 'var(--font-sans)',
              }}
            >
              {label}
            </span>
          </NavLink>
        ))}
      </div>

      {/* Settings at bottom */}
      <NavLink
        to="/settings"
        title="Settings"
        className="flex items-center justify-center w-10 h-10 rounded-lg transition-colors"
        style={{ color: 'var(--color-text-dim)' }}
      >
        <Settings size={16} />
      </NavLink>
    </nav>
  )
}
