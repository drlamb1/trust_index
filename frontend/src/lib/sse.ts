// SSE utilities for EdgeFinder
//
// Two SSE patterns:
//   1. Standard EventSource (GET) — simulation stream /simulation/stream
//      Note: EventSource doesn't support custom headers, so the simulation stream
//      is unauthenticated (it only returns public event log data — no sensitive info).
//   2. POST → text/event-stream  — chat endpoint /api/chat
//      Uses Bearer token in Authorization header.

import type { ChatSSEEvent, PersonaName } from '@/types/api'
import { getToken } from '@/lib/api'

const BASE = import.meta.env.VITE_API_URL || ''

// ─── Standard EventSource (simulation feed) ───
// /simulation/stream is public (no auth required) — it only shows agent activity log

export function createSimulationStream(
  onEvent: (event: Record<string, unknown>) => void,
  onError?: () => void,
): () => void {
  const es = new EventSource(`${BASE}/simulation/stream`)

  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      onEvent(data)
    } catch { /* skip malformed */ }
  }

  es.onerror = () => {
    onError?.()
    es.close()
  }

  return () => es.close()
}

// ─── POST → streaming chat ───

export async function* streamChat(
  message: string,
  conversationId: string | null,
  persona: PersonaName | null,
): AsyncGenerator<ChatSSEEvent> {
  const token = getToken()
  const res = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      persona,
    }),
  })

  if (!res.ok || !res.body) {
    throw new Error(`Chat request failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    let eventName = ''
    let dataLine = ''

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventName = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        dataLine = line.slice(6).trim()
      } else if (line === '' && eventName && dataLine) {
        try {
          const data = JSON.parse(dataLine)
          yield { event: eventName, data } as ChatSSEEvent
        } catch { /* skip */ }
        eventName = ''
        dataLine = ''
      }
    }
  }
}
