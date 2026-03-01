// Settings — account info, password change, sign out

import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { auth, clearToken } from '@/lib/api'

export default function Settings() {
  const navigate = useNavigate()
  const user = useAuthStore(s => s.user)
  const logout = useAuthStore(s => s.logout)

  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [pwMsg, setPwMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [changing, setChanging] = useState(false)

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (newPw.length < 8) {
      setPwMsg({ text: 'Password must be at least 8 characters.', ok: false })
      return
    }
    setChanging(true)
    setPwMsg(null)
    try {
      await auth.changePassword(currentPw, newPw)
      setPwMsg({ text: 'Password changed.', ok: true })
      setCurrentPw('')
      setNewPw('')
    } catch (err: unknown) {
      setPwMsg({ text: err instanceof Error ? err.message : 'Failed to change password.', ok: false })
    } finally {
      setChanging(false)
    }
  }

  const handleSignOut = () => {
    logout()
    clearToken()
    navigate('/login')
  }

  const inputStyle: React.CSSProperties = {
    background: 'hsl(228 15% 14%)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
    fontFamily: 'var(--font-sans)',
    fontSize: 12,
    borderRadius: 6,
    padding: '8px 12px',
    outline: 'none',
    width: '100%',
  }

  return (
    <div style={{ maxWidth: 480 }} className="animate-entry">
      <h1 style={{ fontFamily: 'var(--font-sans)', fontSize: 18, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 24 }}>
        Settings
      </h1>

      {/* Account Info */}
      <section className="glass" style={{ padding: '20px 24px', marginBottom: 16 }}>
        <h2 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 12 }}>
          Account
        </h2>
        <div className="flex flex-col gap-2">
          {[
            { label: 'Email', value: user?.email },
            { label: 'Username', value: user?.username },
            { label: 'Role', value: user?.role },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-center justify-between" style={{ padding: '4px 0' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
                {label}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-text-primary)' }}>
                {value ?? '—'}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Change Password */}
      <section className="glass" style={{ padding: '20px 24px', marginBottom: 16 }}>
        <h2 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 12 }}>
          Change Password
        </h2>
        <form onSubmit={handleChangePassword} className="flex flex-col gap-3">
          <input
            type="password"
            placeholder="Current password"
            value={currentPw}
            onChange={e => setCurrentPw(e.target.value)}
            style={inputStyle}
            required
          />
          <input
            type="password"
            placeholder="New password (min 8 characters)"
            value={newPw}
            onChange={e => setNewPw(e.target.value)}
            style={inputStyle}
            required
            minLength={8}
          />
          <button
            type="submit"
            disabled={changing || !currentPw || !newPw}
            style={{
              background: 'var(--color-amber-muted)',
              border: '1px solid var(--color-amber-dim)',
              color: 'var(--color-amber)',
              borderRadius: 6, padding: '8px 16px',
              fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 600,
              cursor: changing ? 'not-allowed' : 'pointer',
              opacity: changing ? 0.5 : 1,
            }}
          >
            {changing ? 'Changing…' : 'Change Password'}
          </button>
          {pwMsg && (
            <div style={{
              fontSize: 11, fontFamily: 'var(--font-sans)',
              color: pwMsg.ok ? 'var(--color-success)' : 'var(--color-danger)',
            }}>
              {pwMsg.text}
            </div>
          )}
        </form>
      </section>

      {/* Session */}
      <section className="glass" style={{ padding: '20px 24px', marginBottom: 16 }}>
        <h2 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 12 }}>
          Session
        </h2>
        <button
          onClick={handleSignOut}
          style={{
            background: 'transparent',
            border: '1px solid var(--color-danger)',
            color: 'var(--color-danger)',
            borderRadius: 6, padding: '8px 16px',
            fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 600,
            cursor: 'pointer', width: '100%',
          }}
        >
          Sign Out
        </button>
      </section>

      {/* About */}
      <section className="glass-sm" style={{ padding: '12px 16px' }}>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-dim)' }}>
          EdgeFinder v0.6 ·{' '}
          <Link to="/guide" style={{ color: 'var(--color-amber)', textDecoration: 'none' }}>
            Guide
          </Link>
        </div>
      </section>
    </div>
  )
}
