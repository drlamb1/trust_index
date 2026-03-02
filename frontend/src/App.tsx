import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Analytics } from '@vercel/analytics/react'
import { useAuthStore } from '@/stores/authStore'
import Layout from '@/components/layout/Layout'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import SimulationLab from '@/pages/SimulationLab'
import Chat from '@/pages/Chat'
import LearningJournal from '@/pages/LearningJournal'
import Briefing from '@/pages/Briefing'
import TickerDetail from '@/pages/TickerDetail'
import Guide from '@/pages/Guide'
import Settings from '@/pages/Settings'

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
                    <Route path="/tickers/:symbol" element={<TickerDetail />} />
                    <Route path="/guide" element={<Guide />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </Layout>
              </RequireAuth>
            }
          />
        </Routes>
        <Analytics />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
