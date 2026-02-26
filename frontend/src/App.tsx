import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/authStore'
import Layout from '@/components/layout/Layout'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import SimulationLab from '@/pages/SimulationLab'
import Chat from '@/pages/Chat'
import LearningJournal from '@/pages/LearningJournal'
import Briefing from '@/pages/Briefing'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/*"
            element={
              <RequireAuth>
                <Layout>
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/simulation" element={<SimulationLab />} />
                    <Route path="/chat" element={<Chat />} />
                    <Route path="/journal" element={<LearningJournal />} />
                    <Route path="/briefing" element={<Briefing />} />
                    <Route path="/settings" element={<div style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', padding: 40 }}>Settings — coming soon</div>} />
                  </Routes>
                </Layout>
              </RequireAuth>
            }
          />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
