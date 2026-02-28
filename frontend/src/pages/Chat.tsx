// Chat — Conversational interface with all 8 personas
// SSE streaming via fetch + ReadableStream
// Persona tabs, tool result cards, KaTeX math, markdown

import { useState, useRef, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Send, ChevronDown, ChevronUp } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { PERSONAS, CHAT_PERSONAS } from '@/lib/personas'
import { streamChat } from '@/lib/sse'
import { getToken } from '@/lib/api'
import type { PersonaName } from '@/types/api'

// ─── Tool Result Card ───

function ToolResultCard({ name, result }: { name: string; result: Record<string, unknown> }) {
  const [open, setOpen] = useState(false)
  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        border: `1px solid var(--color-amber-dim)`,
        borderLeft: `3px solid var(--color-amber)`,
        background: 'var(--color-amber-muted)',
        marginTop: 8,
      }}
    >
      <button
        className="w-full flex items-center justify-between px-3 py-2"
        onClick={() => setOpen(!open)}
        style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--color-amber)' }}
      >
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600 }}>
          ⚡ {name}
        </span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <pre
          style={{
            margin: 0,
            padding: '8px 12px',
            fontSize: 10,
            fontFamily: 'var(--font-mono)',
            color: 'var(--color-text-muted)',
            overflowX: 'auto',
            background: 'transparent',
            borderTop: '1px solid var(--color-amber-dim)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  )
}

// ─── Message Bubble ───

interface MessagePart {
  type: 'text' | 'tool_result'
  text?: string
  toolName?: string
  toolResult?: Record<string, unknown>
}

function MessageBubble({
  role,
  parts,
  persona,
  isStreaming,
}: {
  role: 'user' | 'assistant'
  parts: MessagePart[]
  persona?: PersonaName
  isStreaming?: boolean
}) {
  const personaInfo = persona ? PERSONAS[persona] : null

  if (role === 'user') {
    return (
      <div className="flex justify-end" style={{ marginBottom: 12 }}>
        <div
          style={{
            maxWidth: '70%',
            padding: '10px 14px',
            borderRadius: '12px 12px 2px 12px',
            background: 'hsl(228 15% 16%)',
            border: '1px solid var(--color-border)',
            fontFamily: 'var(--font-sans)',
            fontSize: 13,
            color: 'var(--color-text-primary)',
            lineHeight: 1.6,
          }}
        >
          {parts[0]?.text}
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-3" style={{ marginBottom: 16 }}>
      {/* Persona badge */}
      <div
        className="flex-shrink-0 flex items-center justify-center rounded-lg"
        style={{
          width: 28, height: 28, marginTop: 2,
          background: personaInfo ? personaInfo.color + '20' : 'hsl(228 15% 14%)',
          border: `1px solid ${personaInfo ? personaInfo.color + '40' : 'var(--color-border)'}`,
          fontFamily: 'var(--font-mono)',
          fontSize: 11, fontWeight: 700,
          color: personaInfo?.color ?? 'var(--color-text-muted)',
        }}
      >
        {personaInfo?.icon ?? 'A'}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Persona name */}
        {personaInfo && (
          <div style={{
            fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600,
            color: personaInfo.color, marginBottom: 4,
          }}>
            {personaInfo.display_name}
          </div>
        )}

        {/* Message content */}
        {parts.map((part, i) => {
          if (part.type === 'tool_result' && part.toolName && part.toolResult) {
            return <ToolResultCard key={i} name={part.toolName} result={part.toolResult} />
          }
          return (
            <div
              key={i}
              className={isStreaming && i === parts.length - 1 ? 'streaming-cursor' : ''}
              style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--color-text-primary)', lineHeight: 1.7 }}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code: ({ children, className }) => (
                    <code style={{
                      fontFamily: 'var(--font-mono)', fontSize: 12,
                      background: 'hsl(228 15% 14%)', padding: '1px 4px',
                      borderRadius: 3, color: 'var(--color-cyan)',
                    }}>
                      {children}
                    </code>
                  ),
                  table: ({ children }) => (
                    <table style={{ borderCollapse: 'collapse', width: '100%', marginTop: 8, fontSize: 11 }}>
                      {children}
                    </table>
                  ),
                  th: ({ children }) => (
                    <th style={{
                      padding: '4px 8px', textAlign: 'left', fontSize: 10,
                      fontFamily: 'var(--font-sans)', fontWeight: 600,
                      color: 'var(--color-text-muted)', letterSpacing: '0.05em',
                      textTransform: 'uppercase', borderBottom: '1px solid var(--color-border)',
                    }}>
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td style={{
                      padding: '4px 8px', borderBottom: '1px solid var(--color-border)',
                      color: 'var(--color-text-primary)', fontFamily: 'var(--font-mono)', fontSize: 11,
                    }}>
                      {children}
                    </td>
                  ),
                }}
              >
                {part.text ?? ''}
              </ReactMarkdown>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Chat Message state ───

interface ChatEntry {
  id: string
  role: 'user' | 'assistant'
  parts: MessagePart[]
  persona?: PersonaName
  isStreaming?: boolean
}

// ─── Main Chat Page ───

const convKey = (persona: PersonaName) => `edgefinder_conv_${persona}`

export default function Chat() {
  const [searchParams] = useSearchParams()
  const { activePersona, setPersona } = useAuthStore()
  const [messages, setMessages] = useState<ChatEntry[]>([])
  const [input, setInput] = useState(searchParams.get('message') ?? '')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Handle persona from URL param
  useEffect(() => {
    const p = searchParams.get('persona') as PersonaName | null
    if (p && CHAT_PERSONAS.includes(p)) setPersona(p)
  }, [])

  // Restore conversation for active persona from localStorage
  useEffect(() => {
    const saved = localStorage.getItem(convKey(activePersona))
    if (!saved) {
      setConversationId(null)
      setMessages([])
      return
    }

    setConversationId(saved)
    setIsLoadingHistory(true)

    const headers: Record<string, string> = {}
    const token = getToken()
    if (token) headers['Authorization'] = `Bearer ${token}`

    fetch(`/api/chat/conversations/${saved}/messages`, { headers })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.messages?.length) { setMessages([]); return }
        const restored: ChatEntry[] = []
        for (const msg of data.messages) {
          if (msg.role === 'user') {
            restored.push({
              id: `u-${msg.id}`,
              role: 'user',
              parts: [{ type: 'text', text: msg.content ?? '' }],
            })
          } else if (msg.role === 'assistant') {
            restored.push({
              id: `a-${msg.id}`,
              role: 'assistant',
              parts: [{ type: 'text', text: msg.content ?? '' }],
              persona: (msg.persona as PersonaName) ?? undefined,
            })
          }
        }
        setMessages(restored)
      })
      .catch(() => { setMessages([]) })
      .finally(() => setIsLoadingHistory(false))
  }, [activePersona])

  // Persist conversationId per persona whenever it changes
  useEffect(() => {
    if (conversationId) localStorage.setItem(convKey(activePersona), conversationId)
  }, [conversationId, activePersona])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || isLoading) return

    setInput('')
    setIsLoading(true)

    // Add user message
    const userEntry: ChatEntry = {
      id: `u-${Date.now()}`,
      role: 'user',
      parts: [{ type: 'text', text }],
    }
    setMessages(prev => [...prev, userEntry])

    // Add placeholder assistant message
    const assistantId = `a-${Date.now()}`
    const assistantEntry: ChatEntry = {
      id: assistantId,
      role: 'assistant',
      parts: [{ type: 'text', text: '' }],
      persona: activePersona,
      isStreaming: true,
    }
    setMessages(prev => [...prev, assistantEntry])

    try {
      let currentText = ''
      let currentPersona = activePersona

      for await (const event of streamChat(text, conversationId, activePersona)) {
        switch (event.event) {
          case 'meta':
            setConversationId(event.data.conversation_id)
            currentPersona = event.data.persona as PersonaName
            setMessages(prev => prev.map(m =>
              m.id === assistantId ? { ...m, persona: currentPersona } : m
            ))
            break

          case 'token':
            currentText += event.data.text
            setMessages(prev => prev.map(m => {
              if (m.id !== assistantId) return m
              // Update only the last text part — preserves earlier thinking text and tool cards
              const parts = [...m.parts]
              for (let i = parts.length - 1; i >= 0; i--) {
                if (parts[i].type === 'text') {
                  parts[i] = { type: 'text', text: currentText }
                  break
                }
              }
              return { ...m, parts }
            }))
            break

          case 'tool_result':
            setMessages(prev => prev.map(m => {
              if (m.id !== assistantId) return m
              const newParts: MessagePart[] = [
                ...m.parts,
                { type: 'tool_result', toolName: event.data.name, toolResult: event.data.result },
              ]
              return { ...m, parts: newParts }
            }))
            break

          case 'round_start':
            // New Claude response round after tool execution — freeze the thinking text
            // and start a fresh text accumulator so both are visible
            currentText = ''
            setMessages(prev => prev.map(m => {
              if (m.id !== assistantId) return m
              return { ...m, parts: [...m.parts, { type: 'text', text: '' }] }
            }))
            break

          case 'done':
            setMessages(prev => prev.map(m =>
              m.id === assistantId ? { ...m, isStreaming: false } : m
            ))
            break

          case 'error':
            setMessages(prev => prev.map(m =>
              m.id === assistantId
                ? { ...m, parts: [{ type: 'text', text: `Error: ${event.data.message}` }], isStreaming: false }
                : m
            ))
            break
        }
      }
    } catch (err) {
      setMessages(prev => prev.map(m =>
        m.id === assistantId
          ? { ...m, parts: [{ type: 'text', text: `Connection error: ${err}` }], isStreaming: false }
          : m
      ))
    } finally {
      setIsLoading(false)
    }
  }, [input, isLoading, activePersona, conversationId])

  return (
    <div className="flex flex-col" style={{ height: 'calc(100vh - 80px)' }}>
      {/* Persona selector */}
      <div
        className="flex gap-2 pb-4"
        style={{ overflowX: 'auto', flexShrink: 0 }}
      >
        {CHAT_PERSONAS.map(pName => {
          const p = PERSONAS[pName]
          const isActive = activePersona === pName
          return (
            <button
              key={pName}
              onClick={() => setPersona(pName)}
              className="flex items-center gap-2 px-3 py-2 rounded-lg flex-shrink-0 transition-colors"
              style={{
                fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 500,
                border: `1px solid ${isActive ? p.color + '60' : 'var(--color-border)'}`,
                background: isActive ? p.color + '18' : 'hsl(228 18% 10%)',
                color: isActive ? p.color : 'var(--color-text-muted)',
                cursor: 'pointer',
                borderBottom: isActive ? `2px solid ${p.color}` : '2px solid transparent',
              }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 11 }}>
                {p.icon}
              </span>
              {p.display_name}
            </button>
          )
        })}
      </div>

      {/* Message thread */}
      <div
        className="flex-1 overflow-y-auto"
        style={{ padding: '8px 0', marginBottom: 8 }}
      >
        {isLoadingHistory && (
          <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            restoring conversation…
          </div>
        )}
        {!isLoadingHistory && messages.length === 0 && (
          <div
            className="flex flex-col items-center justify-center h-full"
            style={{ color: 'var(--color-text-dim)', textAlign: 'center' }}
          >
            <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.3 }}>
              {PERSONAS[activePersona].icon}
            </div>
            <div style={{ fontFamily: 'var(--font-sans)', fontSize: 14, marginBottom: 4, color: 'var(--color-text-muted)' }}>
              {PERSONAS[activePersona].display_name}
            </div>
            <div style={{ fontFamily: 'var(--font-sans)', fontSize: 12 }}>
              Send a message to start the conversation
            </div>
          </div>
        )}
        {!isLoadingHistory && messages.length > 0 && (
          <div style={{ textAlign: 'center', paddingBottom: 12 }}>
            <button
              onClick={() => {
                localStorage.removeItem(convKey(activePersona))
                setConversationId(null)
                setMessages([])
              }}
              style={{
                background: 'transparent', border: '1px solid var(--color-border)',
                borderRadius: 6, padding: '3px 10px', cursor: 'pointer',
                fontFamily: 'var(--font-mono)', fontSize: 10,
                color: 'var(--color-text-dim)',
              }}
            >
              new conversation
            </button>
          </div>
        )}
        {messages.map(m => (
          <MessageBubble key={m.id} {...m} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div
        className="glass flex gap-3 items-end"
        style={{ padding: '12px 16px', flexShrink: 0 }}
      >
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              sendMessage()
            }
          }}
          placeholder={`Message ${PERSONAS[activePersona].display_name}…`}
          rows={1}
          style={{
            flex: 1, background: 'transparent', border: 'none', outline: 'none', resize: 'none',
            fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--color-text-primary)',
            lineHeight: 1.5, maxHeight: 120, overflowY: 'auto',
          }}
        />
        <button
          onClick={sendMessage}
          disabled={!input.trim() || isLoading}
          style={{
            flexShrink: 0, width: 32, height: 32, borderRadius: 8,
            background: input.trim() && !isLoading ? 'var(--color-amber)' : 'var(--color-amber-muted)',
            border: 'none', cursor: input.trim() && !isLoading ? 'pointer' : 'not-allowed',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <Send size={13} style={{ color: input.trim() && !isLoading ? '#000' : 'var(--color-amber-dim)' }} />
        </button>
      </div>
    </div>
  )
}
