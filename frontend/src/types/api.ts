// EdgeFinder API Types — mirrors Python backend models

export interface User {
  id: number
  email: string
  username: string
  role: 'admin' | 'member' | 'viewer'
  is_active: boolean
  daily_token_budget: number
  tokens_used_today: number
}

export interface Ticker {
  id: number
  symbol: string
  name: string | null
  sector: string | null
  in_watchlist: boolean
  in_sp500: boolean
  thesis_tags: string[] | null
}

// ─── Market Pulse ───

export interface MacroIndicator {
  series_id: string
  date: string
  value: number
  series_name: string | null
}

export interface MacroPulseCard {
  series_id: string
  label: string
  value_str: string
  change_str: string | null
  direction: 'up' | 'down' | 'flat'
  as_of: string | null
}

// ─── Ticker Detail ───

export interface TickerSummary {
  id: number
  symbol: string
  name: string | null
  sector: string | null
  in_watchlist: boolean
  latest_close: number | null
  daily_change_pct: number | null
  price_date: string | null
  technicals: {
    date: string
    rsi_14: number | null
    macd: number | null
    macd_signal: number | null
    macd_histogram: number | null
    macd_direction: 'bull' | 'bear'
    bb_position: 'above upper' | 'in band' | 'below lower' | null
    bb_upper: number | null
    bb_lower: number | null
    sma_20: number | null
    sma_50: number | null
    sma_200: number | null
    volume_ratio_20d: number | null
  } | null
}

export interface TickerPriceBar {
  date: string
  open: number | null
  high: number | null
  low: number | null
  close: number
  volume: number | null
}

export interface TickerAlert {
  id: number
  alert_type: string
  severity: string
  score: number | null
  title: string
  created_at: string
}

export interface WatchlistMover {
  symbol: string
  name: string | null
  change_pct: number
  close: number
}

// ─── Simulation Engine ───

export type ThesisStatus = 'proposed' | 'backtesting' | 'paper_live' | 'retired' | 'killed'

export interface SimulatedThesis {
  id: number
  name: string
  thesis_text: string
  status: ThesisStatus
  generated_by: string
  time_horizon_days: number | null
  ticker_ids: number[] | null
  ticker_symbol: string | null
  ticker_symbols: string[]
  created_at: string
  retired_at: string | null
  retirement_reason: string | null
  entry_criteria: Record<string, unknown> | null
  exit_criteria: Record<string, unknown> | null
  expected_catalysts: string[] | null
  risk_factors: string[] | null
}

export interface BacktestRun {
  id: number
  thesis_id: number
  ticker_id: number
  thesis_name?: string | null
  start_date: string
  end_date: string
  sharpe: number | null
  sortino: number | null
  max_drawdown: number | null
  win_rate: number | null
  profit_factor: number | null
  total_trades: number | null
  monte_carlo_p_value: number | null
  ran_at: string
}

export interface PaperPosition {
  id: number
  ticker: string
  thesis: string
  side: 'long' | 'short'
  shares: number
  entry_price: number
  current_price: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  entry_date: string
  stop_loss: number | null
  take_profit: number | null
}

export interface PortfolioSummary {
  portfolio_name: string
  initial_capital: number
  total_value: number
  cash: number
  positions_value: number
  total_pnl: number
  total_pnl_pct: number
  open_positions: number
  positions: PaperPosition[]
  by_thesis: Record<string, { pnl: number; pnl_pct: number; positions: number }>
  disclaimer: string
}

export interface HestonParams {
  ticker: string
  as_of: string
  v0: number
  kappa: number
  theta: number
  sigma_v: number
  rho: number
  calibration_error: number | null
  feller_satisfied: boolean
  interpretation: {
    current_vol: string
    long_run_vol: string
    leverage_effect: string
  }
}

export interface VolSurface {
  ticker: string
  as_of: string
  model_type: string
  surface_data: {
    moneyness: number[]
    expiries: number[]
    ivs: (number | null)[][]
    atm_iv: number | null
    skew_25d: number | null
  } | null
  calibration_error: number | null
}

export interface SimulationLog {
  id: number
  thesis_id: number | null
  agent_name: string
  event_type: string
  event_data: Record<string, unknown> | null
  created_at: string
}

export interface AgentMemory {
  id: number
  agent_name: string
  memory_type: 'insight' | 'pattern' | 'failure' | 'success' | 'lesson_taught'
  content: string
  confidence: number
  evidence: Record<string, unknown> | null
  access_count: number
  created_at: string
}

export interface DailyBriefingResponse {
  id: number
  date: string
  edger_synthesis: string | null
  lesson_taught: string | null
  content_md: string | null
  delivered_at: string | null
}

export interface SimulationStats {
  theses: {
    total: number
    by_status: Partial<Record<ThesisStatus, number>>
  }
  backtests: number
  avg_win_rate: number | null
  avg_sharpe: number | null
  portfolio: {
    value: number
    pnl: number
    pnl_pct: number
  }
  memories: number
  log_entries: number
  disclaimer: string
}

// ─── Chat ───

export type PersonaName = 'edge' | 'analyst' | 'thesis' | 'pm' | 'thesis_lord' | 'vol_slayer' | 'heston_cal' | 'deep_hedge' | 'post_mortem'

export interface PersonaInfo {
  name: PersonaName
  display_name: string
  role: string
  color: string
  icon: string
}

export interface Conversation {
  id: string
  title: string | null
  active_persona: PersonaName
  message_count: number
  created_at: string
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result'
  persona: PersonaName | null
  content: string
  tool_name: string | null
  tool_input: Record<string, unknown> | null
  tool_result_data: Record<string, unknown> | null
  created_at: string
}

// SSE event types from /api/chat
export type ChatSSEEvent =
  | { event: 'meta'; data: { conversation_id: string; persona: string; display_name: string; color: string; icon: string } }
  | { event: 'token'; data: { text: string } }
  | { event: 'tool_start'; data: { name: string; input: Record<string, unknown> } }
  | { event: 'tool_result'; data: { name: string; result: Record<string, unknown> } }
  | { event: 'handoff'; data: { target_persona: string; reason: string } }
  | { event: 'round_start'; data: { round: number } }
  | { event: 'done'; data: { input_tokens: number; output_tokens: number; cache_read_tokens: number } }
  | { event: 'error'; data: { message: string } }

// ─── Alerts ───

export interface Alert {
  id: number
  symbol: string
  type: string
  severity: 'green' | 'yellow' | 'red'
  title: string
  body: string | null
  score: number | null
  created_at: string
}
