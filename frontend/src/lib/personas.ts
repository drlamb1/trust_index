import type { PersonaInfo, PersonaName } from '@/types/api'

export const PERSONAS: Record<PersonaName, PersonaInfo> = {
  edge: {
    name: 'edge',
    display_name: 'The Edger',
    role: 'Generalist & Translator',
    color: '#ff4f81',
    icon: 'E',
  },
  analyst: {
    name: 'analyst',
    display_name: 'The Analyst',
    role: 'Data Intelligence',
    color: '#7c85f5',
    icon: 'A',
  },
  thesis: {
    name: 'thesis',
    display_name: 'Thesis Genius',
    role: 'Thesis Architect',
    color: '#d29922',
    icon: 'T',
  },
  pm: {
    name: 'pm',
    display_name: 'The PM',
    role: 'Platform & Features',
    color: '#39d0b8',
    icon: 'P',
  },
  thesis_lord: {
    name: 'thesis_lord',
    display_name: 'Thesis Lord',
    role: 'Thesis Lifecycle',
    color: '#d29922',
    icon: 'L',
  },
  vol_slayer: {
    name: 'vol_slayer',
    display_name: 'Vol Slayer',
    role: 'Options & Volatility',
    color: '#00d4ff',
    icon: 'V',
  },
  heston_cal: {
    name: 'heston_cal',
    display_name: 'Heston Cal.',
    role: 'Stochastic Vol Engine',
    color: '#ff6b35',
    icon: 'H',
  },
  deep_hedge: {
    name: 'deep_hedge',
    display_name: 'Deep Hedge',
    role: 'Neural Hedging Lab',
    color: '#39ff14',
    icon: 'D',
  },
  post_mortem: {
    name: 'post_mortem',
    display_name: 'Post-Mortem',
    role: 'Institutional Memory',
    color: '#9b59b6',
    icon: 'M',
  },
}

export const CHAT_PERSONAS: PersonaName[] = ['edge', 'analyst', 'thesis', 'pm', 'thesis_lord', 'vol_slayer', 'heston_cal', 'deep_hedge', 'post_mortem']

// Maps agent names from simulation log to display colors
export function agentColor(agentName: string): string {
  return PERSONAS[agentName as PersonaName]?.color ?? '#8b949e'
}
