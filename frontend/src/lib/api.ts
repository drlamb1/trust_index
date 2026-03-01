// EdgeFinder typed API client
// Uses Bearer token auth (localStorage) for cross-origin Vercel → Railway requests.
// Cookies don't work cross-origin without SameSite=None + HTTPS on the same domain.

import type {
  AgentMemory,
  Alert,
  Conversation,
  ChatMessage,
  HestonParams,
  MacroPulseCard,
  PortfolioSummary,
  SimulatedThesis,
  SimulationLog,
  SimulationStats,
  ThesisStatus,
  TickerAlert,
  TickerPriceBar,
  TickerSummary,
  User,
  VolSurface,
} from '@/types/api'

const BASE = import.meta.env.VITE_API_URL || ''

// ─── Token storage ───

const TOKEN_KEY = 'ef_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

// ─── Core fetch ───

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string>),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json()
}

// ─── Auth ───

export const auth = {
  login: async (email: string, password: string): Promise<{ access_token: string; user: User }> => {
    // Login doesn't need a token yet — post without auth header
    const res = await fetch(`${BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new Error(`${res.status} ${res.statusText}: ${body}`)
    }
    const data = await res.json()
    if (data.access_token) setToken(data.access_token)
    return data
  },
  me: () => req<User>('/api/auth/me'),
  logout: () => {
    clearToken()
    return Promise.resolve()
  },
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
}

// ─── Macro ───

export const macro = {
  pulse: () => req<MacroPulseCard[]>('/api/macro/pulse'),
}

// ─── Ticker ───

export const tickers = {
  list: () => req<Array<{ symbol: string; name: string | null }>>('/api/tickers'),
}

export const ticker = {
  summary: (symbol: string) => req<TickerSummary>(`/api/ticker/${symbol}`),
  priceHistory: (symbol: string, days = 90) =>
    req<TickerPriceBar[]>(`/api/ticker/${symbol}/price-history?days=${days}`),
  alerts: (symbol: string) => req<TickerAlert[]>(`/api/ticker/${symbol}/alerts`),
  theses: (symbol: string) => req<SimulatedThesis[]>(`/api/ticker/${symbol}/theses`),
  backtests: (symbol: string) => req<import('@/types/api').BacktestRun[]>(`/api/ticker/${symbol}/backtests`),
}

// ─── Briefing ───

export const briefing = {
  markdown: async (): Promise<string> => {
    const token = getToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`${BASE}/briefing.md`, { headers })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.text()
  },
}

// ─── ML ───

export const ml = {
  status: () => req<Record<string, unknown>>('/api/ml/status'),
}
