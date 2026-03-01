// Briefing — daily market brief, clean reading experience
// react-markdown + remark-gfm, Space Grotesk body, JetBrains Mono for numbers

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { briefing } from '@/lib/api'
import { RefreshCw, GraduationCap, ChevronDown, ChevronUp } from 'lucide-react'

// Maps concept_id → { name, description, difficulty }
const CONCEPTS: Record<string, { name: string; desc: string; level: string }> = {
  sortino_ratio: { name: 'Sortino Ratio', desc: 'Like Sharpe but only penalizes downside vol — upside surprise is fine', level: 'beginner' },
  sharpe_ratio: { name: 'Sharpe Ratio', desc: 'Risk-adjusted return: excess return per unit of total volatility', level: 'beginner' },
  rsi: { name: 'RSI (Relative Strength Index)', desc: 'Momentum oscillator measuring speed of price changes on a 0-100 scale', level: 'beginner' },
  sma_crossover: { name: 'SMA Golden/Death Cross', desc: 'Short-term moving average crosses long-term — trend change signal', level: 'beginner' },
  implied_vol: { name: 'Implied Volatility', desc: "The market's forecast of future price movement, extracted from option prices", level: 'intermediate' },
  vol_skew: { name: 'Volatility Skew', desc: "Why OTM puts cost more than calls — the market's crash insurance premium", level: 'intermediate' },
  monte_carlo: { name: 'Monte Carlo Simulation', desc: 'Running thousands of random futures to estimate probability distributions', level: 'intermediate' },
  mean_reversion: { name: 'Mean Reversion', desc: 'Prices tend to return to their average — the tricky part is knowing which average', level: 'intermediate' },
  heston_model: { name: 'Heston Model', desc: 'Letting volatility itself be random — because vol clusters and has its own dynamics', level: 'advanced' },
  p_value: { name: 'Statistical Significance (p-values)', desc: 'How likely your backtest result happened by random chance', level: 'intermediate' },
  max_drawdown: { name: 'Maximum Drawdown', desc: 'Worst peak-to-trough drop — the pain metric that Sharpe ignores', level: 'beginner' },
  position_sizing: { name: 'Position Sizing', desc: 'How much capital per thesis — the unsexy skill that keeps you alive', level: 'beginner' },
  bollinger_bands: { name: 'Bollinger Bands', desc: 'Price channels based on std dev — tells you if price is unusually stretched', level: 'beginner' },
  term_structure: { name: 'Vol Term Structure', desc: 'How implied vol changes across expiry dates — flat, contango, or backwardation', level: 'intermediate' },
  leverage_effect: { name: 'The Leverage Effect', desc: "Why vol goes up when stocks go down — it's about debt ratios, not psychology", level: 'intermediate' },
  feller_condition: { name: 'Feller Condition', desc: 'When can vol touch zero in Heston? This constraint shapes the entire surface', level: 'advanced' },
  cvar: { name: 'CVaR (Conditional Value at Risk)', desc: "Average loss in the worst X% of scenarios — VaR's smarter sibling", level: 'intermediate' },
  signal_convergence: { name: 'Signal Convergence', desc: 'When multiple independent signals point the same direction — triangulating a position', level: 'beginner' },
  earnings_surprise: { name: 'Earnings Surprise', desc: 'Gap between expected and actual earnings — the reaction matters more than the number', level: 'beginner' },
  insider_buying: { name: 'Insider Buying Signals', desc: 'Officers buying their own stock with real money — the strongest non-public signal', level: 'beginner' },
}

const LEVEL_COLOR: Record<string, string> = {
  beginner: 'var(--color-success)',
  intermediate: 'var(--color-amber)',
  advanced: 'var(--color-cyan)',
}

export default function Briefing() {
  const { data: markdown, isLoading, isError, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['briefing'],
    queryFn: briefing.markdown,
    staleTime: 5 * 60 * 1000,
  })

  const { data: latest } = useQuery({
    queryKey: ['briefing-latest'],
    queryFn: briefing.latest,
    staleTime: 5 * 60 * 1000,
  })

  const [synthOpen, setSynthOpen] = useState(true)

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

      {/* Edger Synthesis + Lesson Taught */}
      {latest?.edger_synthesis && (
        <div style={{ marginTop: 32 }}>
          <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', marginBottom: 24 }} />

          <button
            onClick={() => setSynthOpen(!synthOpen)}
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 8, padding: 0, marginBottom: 16,
              width: '100%',
            }}
          >
            <h2 style={{
              fontSize: 12, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
              color: 'var(--color-cyan)', margin: 0,
            }}>
              The Edger's Take
            </h2>
            {synthOpen ? <ChevronUp size={14} style={{ color: 'var(--color-text-dim)' }} /> : <ChevronDown size={14} style={{ color: 'var(--color-text-dim)' }} />}
          </button>

          {synthOpen && (
            <>
              <div
                style={{
                  fontFamily: 'var(--font-sans)', fontSize: 13, lineHeight: 1.8,
                  color: 'var(--color-text-primary)',
                  background: 'hsl(228 18% 8%)',
                  border: '1px solid var(--color-border)',
                  borderLeft: '3px solid var(--color-cyan)',
                  borderRadius: '0 8px 8px 0',
                  padding: '20px 24px',
                }}
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
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
                  }}
                >
                  {latest.edger_synthesis}
                </ReactMarkdown>
              </div>

              {/* Lesson taught card */}
              {latest.lesson_taught && (() => {
                const concept = CONCEPTS[latest.lesson_taught]
                const level = concept?.level ?? 'intermediate'
                const levelColor = LEVEL_COLOR[level] ?? 'var(--color-text-muted)'
                return (
                  <div
                    style={{
                      marginTop: 16,
                      background: 'hsl(228 18% 10%)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 8,
                      padding: '14px 20px',
                      display: 'flex', alignItems: 'center', gap: 12,
                    }}
                  >
                    <GraduationCap size={18} style={{ color: levelColor, flexShrink: 0 }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{ fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary)' }}>
                          {concept?.name ?? latest.lesson_taught.replace(/_/g, ' ')}
                        </span>
                        <span
                          className="pill"
                          style={{
                            background: levelColor + '20',
                            color: levelColor,
                            border: `1px solid ${levelColor}40`,
                            fontSize: 9,
                          }}
                        >
                          {level}
                        </span>
                      </div>
                      {concept?.desc && (
                        <div style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
                          {concept.desc}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()}
            </>
          )}
        </div>
      )}
    </div>
  )
}
