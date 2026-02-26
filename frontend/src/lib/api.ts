// EdgeFinder typed API client
// All requests include credentials (cookie-based JWT)

import type {
  AgentMemory,
  Alert,
  Conversation,
  ChatMessage,
  HestonParams,
  PortfolioSummary,
  SimulatedThesis,
  SimulationLog,
  SimulationStats,
  ThesisStatus,
  User,
  VolSurface,
} from '@/types/api'

const BASE = import.meta.env.VITE_API_URL || ''

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json()
}

// ─── Auth ───

export const auth = {
  login: (email: string, password: string) =>
    req<{ access_token: string; user: User }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  me: () => req<User>('/api/auth/me'),
  logout: () => req('/api/auth/logout', { method: 'POST' }),
  changePassword: (current_password: string, new_password: string) =>
    req('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),
}

// ─── Simulation ───

export const simulation = {
  stats: () => req<SimulationStats>('/api/simulation/stats'),
  portfolio: () => req<PortfolioSummary>('/api/simulation/portfolio'),
  theses: (status?: ThesisStatus, limit = 20) =>
    req<SimulatedThesis[]>(`/api/simulation/theses?limit=${limit}${status ? `&status=${status}` : ''}`),
  thesis: (id: number) => req<SimulatedThesis>(`/api/simulation/theses/${id}`),
  volSurface: (ticker: string) => req<VolSurface>(`/api/simulation/vol-surface/${ticker}`),
  heston: (ticker: string) => req<HestonParams>(`/api/simulation/heston/${ticker}`),
  decisionLog: (params?: { thesis_id?: number; event_type?: string; limit?: number }) => {
    const q = new URLSearchParams()
    if (params?.thesis_id) q.set('thesis_id', String(params.thesis_id))
    if (params?.event_type) q.set('event_type', params.event_type)
    if (params?.limit) q.set('limit', String(params.limit))
    return req<SimulationLog[]>(`/api/simulation/decision-log?${q}`)
  },
  memories: (params?: { agent_name?: string; memory_type?: string; limit?: number }) => {
    const q = new URLSearchParams()
    if (params?.agent_name) q.set('agent_name', params.agent_name)
    if (params?.memory_type) q.set('memory_type', params.memory_type)
    if (params?.limit) q.set('limit', String(params.limit))
    return req<AgentMemory[]>(`/api/simulation/memories?${q}`)
  },
}

// ─── Chat ───

export const chat = {
  conversations: () => req<Conversation[]>('/api/chat/conversations'),
  messages: (id: string) => req<ChatMessage[]>(`/api/chat/conversations/${id}/messages`),
  // Chat itself uses fetch streaming — see lib/sse.ts
}

// ─── Data / Market ───

export const market = {
  recentAlerts: (hours = 24) =>
    req<{ alerts: Alert[]; count: number }>(`/api/chat/…`).catch(() => ({ alerts: [], count: 0 })),
}

// ─── Briefing ───

export const briefing = {
  markdown: () =>
    fetch(`${BASE}/briefing.md`, { credentials: 'include' }).then(r => r.text()),
}
