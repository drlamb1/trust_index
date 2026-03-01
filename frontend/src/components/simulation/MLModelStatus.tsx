// ML Model Status — shows active model versions, metrics, training info

import { useQuery } from '@tanstack/react-query'
import { ml } from '@/lib/api'
import { timeAgo } from '@/lib/timeAgo'

interface ModelInfo {
  active: boolean
  version?: number
  trained_at?: string | null
  size_kb?: number
  format?: string
  message?: string
}

export default function MLModelStatus() {
  const { data, isLoading } = useQuery({
    queryKey: ['ml-status'],
    queryFn: ml.status,
    staleTime: 5 * 60_000,
  })

  if (isLoading) {
    return <div style={{ color: 'var(--color-text-dim)', fontSize: 11 }}>Loading ML status…</div>
  }

  if (!data) {
    return <div style={{ color: 'var(--color-text-dim)', fontSize: 11, fontFamily: 'var(--font-sans)' }}>ML status unavailable.</div>
  }

  const models: Array<{ key: string; label: string; info: ModelInfo }> = [
    { key: 'sentiment', label: 'Sentiment', info: (data.sentiment ?? { active: false }) as ModelInfo },
    { key: 'signal_ranker', label: 'Signal Ranker', info: (data.signal_ranker ?? { active: false }) as ModelInfo },
    { key: 'deep_hedging', label: 'Deep Hedging', info: (data.deep_hedging ?? { active: false }) as ModelInfo },
  ]

  return (
    <div>
      <h3 style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 12 }}>
        ML Models
      </h3>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr>
            {['Model', 'Version', 'Status', 'Trained', 'Size'].map(h => (
              <th key={h} style={{
                textAlign: 'left', padding: '4px 8px',
                fontFamily: 'var(--font-sans)', fontSize: 9, fontWeight: 600,
                letterSpacing: '0.06em', textTransform: 'uppercase',
                color: 'var(--color-text-dim)', borderBottom: '1px solid var(--color-border)',
              }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {models.map(({ key, label, info }) => (
            <tr key={key}>
              <td style={{ padding: '6px 8px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-primary)', borderBottom: '1px solid var(--color-border)' }}>
                {label}
              </td>
              <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)' }}>
                {info.version != null ? `v${info.version}` : '—'}
              </td>
              <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--color-border)' }}>
                <span
                  className="pill"
                  style={info.active
                    ? { background: 'hsl(142 40% 12%)', color: 'var(--color-success)', border: '1px solid hsl(142 40% 25%)' }
                    : { background: 'hsl(228 15% 14%)', color: 'var(--color-text-dim)', border: '1px solid var(--color-border)' }
                  }
                >
                  {info.active ? 'Active' : 'Inactive'}
                </span>
              </td>
              <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-dim)', borderBottom: '1px solid var(--color-border)' }}>
                {info.trained_at ? timeAgo(info.trained_at) : '—'}
              </td>
              <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-dim)', borderBottom: '1px solid var(--color-border)' }}>
                {info.size_kb != null ? `${info.size_kb.toLocaleString()} KB` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Explain inactive state when no models are active */}
      {models.every(m => !m.info.active) && (
        <div style={{
          marginTop: 12, padding: '10px 12px',
          background: 'hsl(228 18% 9%)',
          border: '1px solid var(--color-border)',
          borderRadius: 6,
          fontFamily: 'var(--font-sans)', fontSize: 10,
          color: 'var(--color-text-dim)', lineHeight: 1.6,
        }}>
          Models train locally and deploy to Railway for inference.
          Feature flags <code style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--color-cyan)' }}>use_local_sentiment_model</code> and <code style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--color-cyan)' }}>signal_ranker_enabled</code> are off by default.
        </div>
      )}
    </div>
  )
}
