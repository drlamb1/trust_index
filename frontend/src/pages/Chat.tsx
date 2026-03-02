// Chat — Conversational interface with all 9 personas
// SSE streaming via fetch + ReadableStream
// Persona tabs, tool result cards, KaTeX math, markdown

import { useState, useRef, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useQuery } from '@tanstack/react-query'
import { Send, ChevronDown, ChevronUp, History, Plus } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { PERSONAS, CHAT_PERSONAS } from '@/lib/personas'
import { streamChat } from '@/lib/sse'
import { BASE, getToken, chat as chatApi } from '@/lib/api'
import { timeAgo } from '@/lib/timeAgo'
import type { PersonaName, Conversation } from '@/types/api'

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

const convKey = (persona: PersonaName) => {
  const uid = useAuthStore.getState().user?.id ?? 0
  return `edgefinder_conv_${uid}_${persona}`
}

export default function Chat() {
  const [searchParams] = useSearchParams()
  const { activePersona, setPersona } = useAuthStore()
  const [messages, setMessages] = useState<ChatEntry[]>([])
  const [input, setInput] = useState(searchParams.get('message') ?? '')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [confirmNewChat, setConfirmNewChat] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Conversation history
  const { data: conversations = [] } = useQuery({
    queryKey: ['chat-conversations'],
    queryFn: chatApi.conversations,
    staleTime: 60_000,
    enabled: historyOpen,
  })

  // Prevent page-level scroll — only the message thread should scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

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

    fetch(`${BASE}/api/chat/conversations/${saved}/messages`, { headers })
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
          case 'meta': {
            const newConvId = event.data.conversation_id as string
            setConversationId(newConvId)
            // Persist immediately — only save when server confirms, never during tab switches
            localStorage.setItem(convKey(activePersona), newConvId)
            currentPersona = event.data.persona as PersonaName
            setMessages(prev => prev.map(m =>
              m.id === assistantId ? { ...m, persona: currentPersona } : m
            ))
            break
          }

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

          case 'handoff': {
            const targetPersona = (event.data as { target_persona: string; reason: string }).target_persona as PersonaName
            const reason = (event.data as { target_persona: string; reason: string }).reason
            const targetName = PERSONAS[targetPersona]?.display_name ?? targetPersona
            setMessages(prev => prev.map(m => {
              if (m.id !== assistantId) return m
              return {
                ...m,
                parts: [
                  ...m.parts,
                  { type: 'text' as const, text: `\n\n---\n**Suggested:** Switch to **${targetName}** tab — ${reason}` },
                ],
              }
            }))
            break
          }

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

  const startNewConversation = useCallback(() => {
    localStorage.removeItem(convKey(activePersona))
    setConversationId(null)
    setMessages([])
    setConfirmNewChat(false)
  }, [activePersona])

  const requestNewConversation = useCallback(() => {
    if (messages.length > 0) {
      setConfirmNewChat(true)
    } else {
      startNewConversation()
    }
  }, [messages.length, startNewConversation])

  const handleConvSelect = (conv: Conversation) => {
    localStorage.setItem(convKey(conv.active_persona), conv.id)
    setHistoryOpen(false)
    if (conv.active_persona === activePersona) {
      // Same persona — useEffect won't fire, reload manually
      setConversationId(conv.id)
      setIsLoadingHistory(true)
      const headers: Record<string, string> = {}
      const token = getToken()
      if (token) headers['Authorization'] = `Bearer ${token}`
      fetch(`${BASE}/api/chat/conversations/${conv.id}/messages`, { headers })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          const msgs = data?.messages ?? (Array.isArray(data) ? data : [])
          const restored: ChatEntry[] = []
          for (const msg of msgs) {
            if (msg.role === 'user') {
              restored.push({ id: `u-${msg.id}`, role: 'user', parts: [{ type: 'text', text: msg.content ?? '' }] })
            } else if (msg.role === 'assistant') {
              restored.push({ id: `a-${msg.id}`, role: 'assistant', parts: [{ type: 'text', text: msg.content ?? '' }], persona: (msg.persona as PersonaName) ?? undefined })
            }
          }
          setMessages(restored)
        })
        .catch(() => setMessages([]))
        .finally(() => setIsLoadingHistory(false))
    } else {
      // Different persona — useEffect on activePersona will reload
      setPersona(conv.active_persona)
    }
  }


  return (
    <div className="flex" style={{ height: 'calc(100vh - 104px)' }}>
      {/* Conversation history panel */}
      {historyOpen && (
        <div
          className="glass flex flex-col"
          style={{
            width: 240, flexShrink: 0, marginRight: 12,
            padding: '12px', overflowY: 'auto',
          }}
        >
          <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
              History
            </span>
            <button
              onClick={requestNewConversation}
              title="New conversation"
              aria-label="New conversation"
              style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--color-text-dim)', padding: 2 }}
            >
              <Plus size={14} />
            </button>
          </div>
          {conversations.length === 0 && (
            <div style={{ fontSize: 11, color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)' }}>
              No conversations yet.
            </div>
          )}
          {conversations.map((conv: Conversation) => {
            const p = PERSONAS[conv.active_persona]
            const isActive = conv.id === conversationId
            return (
              <button
                key={conv.id}
                onClick={() => handleConvSelect(conv)}
                className="w-full text-left rounded-lg"
                style={{
                  padding: '8px 10px', marginBottom: 2,
                  background: isActive ? 'hsl(228 15% 16%)' : 'transparent',
                  border: 'none', cursor: 'pointer',
                  borderLeft: `2px solid ${isActive ? (p?.color ?? 'var(--color-amber)') : 'transparent'}`,
                }}
              >
                <div className="flex items-center gap-2" style={{ marginBottom: 2 }}>
                  <div style={{
                    width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                    background: p?.color ?? 'var(--color-text-dim)',
                  }} />
                  <span style={{
                    fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--color-text-primary)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {conv.title ?? 'Untitled'}
                  </span>
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--color-text-dim)', paddingLeft: 14 }}>
                  {conv.message_count} msgs · {timeAgo(conv.created_at)}
                </div>
              </button>
            )
          })}
        </div>
      )}

      {/* Main chat area */}
      <div className="flex flex-col flex-1" style={{ minWidth: 0, minHeight: 0, overflow: 'hidden' }}>
      {/* Persona selector — sticky at top, compact single-line tabs */}
      <div
        className="flex gap-1.5 pb-3 items-center"
        style={{
          overflowX: 'auto', flexShrink: 0,
          borderBottom: '1px solid var(--color-border)', marginBottom: 8,
          /* Fade hint on right edge when scrollable */
          maskImage: 'linear-gradient(to right, black 90%, transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to right, black 90%, transparent 100%)',
        }}
      >
        <button
          onClick={() => setHistoryOpen(!historyOpen)}
          title="Conversation history"
          aria-label="Conversation history"
          className="flex items-center justify-center rounded-lg flex-shrink-0"
          style={{
            width: 28, height: 28, position: 'relative',
            background: historyOpen ? 'var(--color-amber-muted)' : 'hsl(228 18% 10%)',
            border: `1px solid ${historyOpen ? 'var(--color-amber-dim)' : 'var(--color-border)'}`,
            cursor: 'pointer',
            color: historyOpen ? 'var(--color-amber)' : 'var(--color-text-dim)',
          }}
        >
          <History size={12} />
          {conversations.length > 0 && (
            <span style={{
              position: 'absolute', top: -4, right: -4,
              minWidth: 14, height: 14, borderRadius: 7,
              background: 'var(--color-amber)', color: 'hsl(228 22% 7%)',
              fontFamily: 'var(--font-mono)', fontSize: 8, fontWeight: 700,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: '0 3px',
            }}>
              {conversations.length}
            </span>
          )}
        </button>
        {CHAT_PERSONAS.map(pName => {
          const p = PERSONAS[pName]
          const isActive = activePersona === pName
          return (
            <button
              key={pName}
              onClick={() => setPersona(pName)}
              title={p.role}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg flex-shrink-0 transition-colors"
              style={{
                fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 500,
                border: `1px solid ${isActive ? p.color + '60' : 'var(--color-border)'}`,
                background: isActive ? p.color + '18' : 'hsl(228 18% 10%)',
                color: isActive ? p.color : 'var(--color-text-muted)',
                cursor: 'pointer',
                borderBottom: isActive ? `2px solid ${p.color}` : '2px solid transparent',
                whiteSpace: 'nowrap',
                opacity: isActive ? 1 : 0.7,
              }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 11 }}>
                {p.icon}
              </span>
              <span>{p.display_name}</span>
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
        {/* New conversation button — always accessible */}
        {messages.length > 0 && (
          <button
            onClick={requestNewConversation}
            title="New conversation"
            style={{
              flexShrink: 0, width: 32, height: 32, borderRadius: 8,
              background: 'transparent',
              border: '1px solid var(--color-border)',
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'var(--color-text-dim)',
            }}
          >
            <Plus size={14} />
          </button>
        )}
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
          aria-label="Send message"
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

      {/* New conversation confirmation dialog */}
      {confirmNewChat && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 100,
            background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setConfirmNewChat(false)}
        >
          <div
            className="glass"
            onClick={e => e.stopPropagation()}
            style={{
              padding: '24px 28px', borderRadius: 12, maxWidth: 380,
              border: '1px solid var(--color-border)',
            }}
          >
            <h3 style={{
              fontFamily: 'var(--font-sans)', fontSize: 14, fontWeight: 600,
              color: 'var(--color-text-primary)', marginBottom: 8,
            }}>
              Start a new conversation?
            </h3>
            <p style={{
              fontFamily: 'var(--font-sans)', fontSize: 12,
              color: 'var(--color-text-muted)', marginBottom: 20, lineHeight: 1.5,
            }}>
              Your current conversation will be saved to history.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setConfirmNewChat(false)}
                style={{
                  padding: '6px 16px', borderRadius: 6,
                  background: 'transparent', border: '1px solid var(--color-border)',
                  color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)',
                  fontSize: 12, cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={startNewConversation}
                style={{
                  padding: '6px 16px', borderRadius: 6,
                  background: 'var(--color-amber)', border: 'none',
                  color: '#000', fontFamily: 'var(--font-sans)',
                  fontSize: 12, fontWeight: 600, cursor: 'pointer',
                }}
              >
                New Conversation
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
