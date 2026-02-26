import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { User, PersonaName } from '@/types/api'

interface AuthState {
  user: User | null
  activePersona: PersonaName
  isAuthenticated: boolean
  setUser: (user: User | null) => void
  setPersona: (persona: PersonaName) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      activePersona: 'analyst',
      isAuthenticated: false,

      setUser: (user) => set({ user, isAuthenticated: !!user }),

      setPersona: (persona) => set({ activePersona: persona }),

      logout: () => set({ user: null, isAuthenticated: false, activePersona: 'analyst' }),
    }),
    {
      name: 'ef-auth',
      storage: createJSONStorage(() => sessionStorage),
      // Only persist persona preference and auth state, not full user object
      partialize: (state) => ({
        isAuthenticated: state.isAuthenticated,
        activePersona: state.activePersona,
        user: state.user,
      }),
    },
  ),
)
