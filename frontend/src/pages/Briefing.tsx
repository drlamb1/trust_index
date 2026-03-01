// Briefing — daily market brief, clean reading experience
// react-markdown + remark-gfm, Space Grotesk body, JetBrains Mono for numbers

import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { briefing } from '@/lib/api'
import { RefreshCw } from 'lucide-react'

export default function Briefing() {
  const { data: markdown, isLoading, isError, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['briefing'],
    queryFn: briefing.markdown,
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div style={{ maxWidth: 780 }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 24 }}>
        <h1 style={{ fontFamily: 'var(--font-sans)', fontSize: 18, fontWeight: 600, color: 'var(--color-text-primary)' }}>
          Daily Briefing
        </h1>
        <div className="flex items-center gap-3">
          {dataUpdatedAt > 0 && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-dim)' }}>
              Updated {new Date(dataUpdatedAt).toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => refetch()}
            style={{
              background: 'transparent', border: '1px solid var(--color-border)',
              color: 'var(--color-text-muted)', borderRadius: 6, padding: '4px 10px',
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, fontSize: 11,
              fontFamily: 'var(--font-sans)',
            }}
          >
            <RefreshCw size={11} />
            Refresh
          </button>
        </div>
      </div>

      {isLoading && (
        <div style={{ color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', fontSize: 12 }}>
          Generating briefing…
        </div>
      )}

      {isError && !isLoading && (
        <div style={{ color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', fontSize: 12 }}>
          Briefing unavailable — try refreshing.
        </div>
      )}

      {markdown && (
        <div
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: 13,
            lineHeight: 1.8,
            color: 'var(--color-text-primary)',
          }}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h1: ({ children }) => (
                <h1 style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-text-primary)', marginTop: 32, marginBottom: 12, borderBottom: '1px solid var(--color-border)', paddingBottom: 8 }}>
                  {children}
                </h1>
              ),
              h2: ({ children }) => (
                <h2 style={{
                  fontSize: 12, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
                  color: 'var(--color-amber)', marginTop: 28, marginBottom: 12,
                }}>
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text-primary)', marginTop: 20, marginBottom: 8 }}>
                  {children}
                </h3>
              ),
              p: ({ children }) => (
                <p style={{ marginBottom: 12, color: 'var(--color-text-muted)' }}>{children}</p>
              ),
              strong: ({ children }) => (
                <strong style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>{children}</strong>
              ),
              code: ({ children }) => (
                <code style={{
                  fontFamily: 'var(--font-mono)', fontSize: 12,
                  background: 'hsl(228 15% 13%)', padding: '1px 5px',
                  borderRadius: 3, color: 'var(--color-cyan)',
                }}>
                  {children}
                </code>
              ),
              table: ({ children }) => (
                <div style={{ overflowX: 'auto', marginBottom: 16 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    {children}
                  </table>
                </div>
              ),
              th: ({ children }) => (
                <th style={{
                  padding: '6px 12px', textAlign: 'left', fontSize: 10, fontWeight: 700,
                  letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--color-text-muted)',
                  borderBottom: '1px solid var(--color-border)',
                }}>
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td style={{
                  padding: '6px 12px', borderBottom: '1px solid var(--color-border)',
                  color: 'var(--color-text-primary)', fontFamily: 'var(--font-mono)', fontSize: 11,
                }}>
                  {children}
                </td>
              ),
              hr: () => <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '24px 0' }} />,
              li: ({ children }) => (
                <li style={{ marginBottom: 4, color: 'var(--color-text-muted)' }}>{children}</li>
              ),
            }}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}
