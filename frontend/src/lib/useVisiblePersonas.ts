import { useQuery } from '@tanstack/react-query'
import { chat as chatApi } from '@/lib/api'
import { CHAT_PERSONAS, PERSONAS } from '@/lib/personas'
import type { PersonaName, PersonaInfo } from '@/types/api'

/**
 * Returns the list of personas visible to the current user's role.
 * Fetches from /api/chat/personas (role-filtered) with fallback to static list.
 */
export function useVisiblePersonas() {
  const fallback = CHAT_PERSONAS.map(name => PERSONAS[name])
  const { data } = useQuery({
    queryKey: ['chat-personas'],
    queryFn: chatApi.personas,
    staleTime: 300_000,
  })
  const personas: PersonaInfo[] = data && data.length > 0 ? data : fallback
  const names = personas.map(p => p.name as PersonaName)
  return { names, count: names.length, personas }
}
