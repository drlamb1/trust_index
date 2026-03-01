// Guide — permanent "what is this place" page, written in The Edger's voice
// Static content, no API calls. Accessible from sidebar.

import { Link } from 'react-router-dom'
import { PERSONAS, CHAT_PERSONAS } from '@/lib/personas'

const EDGE_COLOR = '#ff4f81'

function PersonaCard({ name }: { name: string }) {
  const p = PERSONAS[name as keyof typeof PERSONAS]
  if (!p) return null
  return (
    <Link
      to={`/chat?persona=${name}`}
      style={{ textDecoration: 'none' }}
    >
      <div
        className="glass-sm"
        style={{
          padding: '14px 16px',
          borderLeft: `3px solid ${p.color}`,
          cursor: 'pointer',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => (e.currentTarget.style.background = 'hsl(228 18% 14%)')}
        onMouseLeave={e => (e.currentTarget.style.background = '')}
      >
        <div className="flex items-center gap-2" style={{ marginBottom: 4 }}>
          <span style={{
            fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 10,
            color: p.color, background: p.color + '18',
            border: `1px solid ${p.color}40`, borderRadius: 5,
            padding: '1px 6px',
          }}>
            {p.icon}
          </span>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)' }}>
            {p.display_name}
          </span>
        </div>
        <div style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.4 }}>
          {p.role}
        </div>
      </div>
    </Link>
  )
}

const PERSONA_DESCRIPTIONS: Record<string, string> = {
  edge: 'Your front door. Ask anything — market questions, jargon translation, or "what should I look at today?" Handles 80% of what you need and knows when to send you to a specialist.',
  analyst: 'Pulls real data: SEC filings, price history, technicals, sentiment scores, macro indicators. Ask "what does AAPL look like right now?" and get numbers, not opinions.',
  thesis: 'Builds structured investment theses with entry/exit criteria, risk factors, and catalysts. The contrarian thinker who asks "what if everyone is wrong about this?"',
  pm: 'The only persona who talks about the platform itself. Feature requests, bug reports, "I wish this could..." — it all goes here. Your feedback shapes the roadmap.',
  thesis_lord: 'The autonomous engine. Generates theses, backtests them against historical data, manages a simulated paper portfolio, and kills positions that stop working. Mathematical honesty over ego.',
  vol_slayer: 'Reads implied volatility surfaces, spots IV-RV divergences, and translates options skew into plain language. Warning: believes he is Trogdor the Burninator.',
  heston_cal: 'Calibrates stochastic volatility models to live market data. Shows you how the market is pricing future uncertainty — and whether that pricing makes sense.',
  deep_hedge: 'The R&D lab. Teaching neural networks to hedge portfolios using reinforcement learning. Experimental, partially built, and proudly weird.',
  post_mortem: 'Performs forensic autopsies on dead theses. What went wrong, what went right, what should the system learn? Every scar becomes a lesson stored in institutional memory.',
}

export default function Guide() {
  return (
    <div style={{ maxWidth: 780 }} className="animate-entry">
      {/* Hero */}
      <div style={{ marginBottom: 40 }}>
        <div className="flex items-center gap-2" style={{ marginBottom: 16 }}>
          <span style={{
            fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12,
            color: EDGE_COLOR, background: EDGE_COLOR + '18',
            border: `1px solid ${EDGE_COLOR}40`, borderRadius: 6,
            padding: '2px 8px',
          }}>
            E
          </span>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: EDGE_COLOR, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            The Edger's Guide
          </span>
        </div>

        <h1 style={{ fontFamily: 'var(--font-sans)', fontSize: 24, fontWeight: 700, color: 'var(--color-text-primary)', marginBottom: 16, lineHeight: 1.3 }}>
          Welcome to EdgeFinder
        </h1>

        <p style={{ fontFamily: 'var(--font-sans)', fontSize: 14, color: 'var(--color-text-muted)', lineHeight: 1.8, marginBottom: 12 }}>
          You just walked into a market intelligence lab staffed by 9 AI specialists who never sleep,
          never panic-sell, and never take your stock tips personally. They analyze markets, build
          investment theses, test them with simulated money, and learn from their mistakes.
        </p>
        <p style={{ fontFamily: 'var(--font-sans)', fontSize: 14, color: 'var(--color-text-muted)', lineHeight: 1.8 }}>
          I'm The Edger — your front door. Think of me as the person at the party who actually
          introduces you to interesting people instead of leaving you standing by the dip.
        </p>
      </div>

      {/* Your First Hour */}
      <section style={{ marginBottom: 40 }}>
        <h2 style={{
          fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 700,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          color: 'var(--color-amber)', marginBottom: 16,
        }}>
          Your First Hour
        </h2>

        <div className="flex flex-col gap-3">
          {[
            {
              step: '1',
              title: 'Talk to me',
              desc: 'Open Agent Chat and say hi. Tell me what you\'re curious about — a ticker, a sector, a hunch. I\'ll pull data, explain what I find, and point you to the right specialist if you want to go deeper.',
              link: '/chat?persona=edge',
              linkText: 'Open Agent Chat',
            },
            {
              step: '2',
              title: 'Search a ticker',
              desc: 'Type any S&P 500 ticker in the search bar up top. You\'ll get a full research page: price chart, technicals (RSI, MACD, Bollinger Bands), linked theses, alerts, and backtest results.',
              link: null,
              linkText: null,
            },
            {
              step: '3',
              title: 'Explore the constellation',
              desc: 'Those glowing dots on your Dashboard are living investment theses. Click one to see its full thesis text, risk factors, and expected catalysts. Green dots are actively paper-trading. Red ones got killed.',
              link: '/',
              linkText: 'Go to Dashboard',
            },
          ].map(({ step, title, desc, link, linkText }) => (
            <div key={step} className="glass-sm" style={{ padding: '16px 20px' }}>
              <div className="flex items-start gap-3">
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700,
                  color: 'var(--color-amber)', minWidth: 20,
                }}>
                  {step}.
                </span>
                <div>
                  <div style={{ fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>
                    {title}
                  </div>
                  <div style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.6, marginBottom: link ? 8 : 0 }}>
                    {desc}
                  </div>
                  {link && (
                    <Link to={link} style={{ fontSize: 11, color: 'var(--color-amber)', textDecoration: 'none', fontFamily: 'var(--font-sans)' }}>
                      {linkText} →
                    </Link>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Meet the Crew */}
      <section style={{ marginBottom: 40 }}>
        <h2 style={{
          fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 700,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          color: 'var(--color-amber)', marginBottom: 8,
        }}>
          Meet the Crew
        </h2>
        <p style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--color-text-dim)', marginBottom: 16 }}>
          Click any persona to start a conversation. They know about each other and will suggest handoffs when you hit the edge of their lane.
        </p>

        <div className="flex flex-col gap-2">
          {CHAT_PERSONAS.map(name => {
            const desc = PERSONA_DESCRIPTIONS[name]
            const p = PERSONAS[name]
            return (
              <Link key={name} to={`/chat?persona=${name}`} style={{ textDecoration: 'none' }}>
                <div
                  className="glass-sm"
                  style={{
                    padding: '14px 16px',
                    borderLeft: `3px solid ${p.color}`,
                    cursor: 'pointer',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'hsl(228 18% 14%)')}
                  onMouseLeave={e => (e.currentTarget.style.background = '')}
                >
                  <div className="flex items-center gap-2" style={{ marginBottom: 4 }}>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 10,
                      color: p.color, background: p.color + '18',
                      border: `1px solid ${p.color}40`, borderRadius: 5,
                      padding: '1px 6px',
                    }}>
                      {p.icon}
                    </span>
                    <span style={{ fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)' }}>
                      {p.display_name}
                    </span>
                    <span style={{ fontFamily: 'var(--font-sans)', fontSize: 10, color: 'var(--color-text-dim)' }}>
                      {p.role}
                    </span>
                  </div>
                  <div style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
                    {desc}
                  </div>
                </div>
              </Link>
            )
          })}
        </div>
      </section>

      {/* What You're Looking At */}
      <section style={{ marginBottom: 40 }}>
        <h2 style={{
          fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 700,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          color: 'var(--color-amber)', marginBottom: 16,
        }}>
          What You're Looking At
        </h2>

        <div className="flex flex-col gap-2">
          {[
            { name: 'Dashboard', desc: 'Your home base. Market Pulse shows macro data (fed funds, yields, CPI). The Thesis Constellation maps active theses as a force-directed graph. The Intelligence Feed streams real-time agent activity.' },
            { name: 'Simulation Lab', desc: 'The engine room. Heston model calibrations, paper portfolio positions, volatility surfaces. Everything the autonomous agents are doing under the hood.' },
            { name: 'Agent Chat', desc: 'Where you talk to the 9 personas. Each one has its own conversation thread. Switch tabs to switch specialists. They share context and suggest handoffs.' },
            { name: 'Learning Journal', desc: 'Institutional memory. Insights, patterns, failures, and successes that the agents have extracted from their work. Searchable and filterable.' },
            { name: 'Daily Briefing', desc: 'A generated market summary covering macro conditions, active theses, recent agent activity, and anything worth watching today.' },
          ].map(({ name, desc }) => (
            <div key={name} className="glass-sm" style={{ padding: '12px 16px' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary)' }}>
                {name}
              </span>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-dim)', marginLeft: 8 }}>
                — {desc}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Simulation disclaimer */}
      <section style={{ marginBottom: 40 }}>
        <div className="glass-sm" style={{ padding: '16px 20px', borderLeft: '3px solid var(--color-amber)' }}>
          <div style={{
            fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 700,
            letterSpacing: '0.08em', textTransform: 'uppercase',
            color: 'var(--color-amber)', marginBottom: 8,
          }}>
            This is a simulation
          </div>
          <div style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
            Every trade, portfolio position, and P&L number on this platform uses simulated play money.
            No real orders are placed. No real money is at risk. The theses, backtests, and paper
            positions exist to help you think about markets — not to manage your actual portfolio.
            Always do your own research before making any investment decisions.
          </div>
        </div>
      </section>
    </div>
  )
}
