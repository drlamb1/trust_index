import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Zap } from 'lucide-react'
import { auth } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'

export default function Login() {
  const navigate = useNavigate()
  const setUser = useAuthStore(s => s.setUser)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await auth.login(email, password)
      setUser(res.user)
      navigate('/')
    } catch (err) {
      setError('Invalid credentials. Check email and password.')
    } finally {
      setLoading(false)
    }
  }

  const inputStyle = {
    width: '100%', padding: '10px 14px', borderRadius: 8,
    background: 'hsl(228 18% 11%)', border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)', fontSize: 13, outline: 'none',
  }

  return (
    <div className="flex items-center justify-center" style={{ minHeight: '100vh' }}>
      <div className="glass" style={{ padding: 40, width: 360 }}>
        {/* Logo */}
        <div className="flex items-center gap-3 justify-center" style={{ marginBottom: 32 }}>
          <div
            className="flex items-center justify-center rounded-xl"
            style={{ width: 40, height: 40, background: 'var(--color-amber-muted)', border: '1px solid var(--color-amber-dim)' }}
          >
            <Zap size={18} style={{ color: 'var(--color-amber)' }} />
          </div>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: 22, fontWeight: 600 }}>
            <span style={{ color: 'var(--color-text-primary)' }}>Edge</span>
            <span style={{ color: 'var(--color-amber)' }}>Finder</span>
          </div>
        </div>

        <div style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--color-text-muted)', textAlign: 'center', marginBottom: 24 }}>
          Market Intelligence Lab
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
            style={inputStyle}
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            style={inputStyle}
          />

          {error && (
            <div style={{ color: 'var(--color-danger)', fontSize: 12, fontFamily: 'var(--font-sans)' }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              marginTop: 8, padding: '10px', borderRadius: 8,
              background: loading ? 'var(--color-amber-muted)' : 'var(--color-amber)',
              border: 'none', color: loading ? 'var(--color-amber)' : '#000',
              fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
