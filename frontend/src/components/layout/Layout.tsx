import { useState, type ReactNode } from 'react'
import { DesktopSidebar, MobileDrawer } from './Sidebar'
import TopBar from './TopBar'
import { useIsMobile } from '@/lib/useIsMobile'

export default function Layout({ children }: { children: ReactNode }) {
  const isMobile = useIsMobile()
  const [drawerOpen, setDrawerOpen] = useState(false)

  return (
    <div style={{ minHeight: '100vh' }}>
      {isMobile ? (
        <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      ) : (
        <DesktopSidebar />
      )}
      <TopBar isMobile={isMobile} onMenuToggle={() => setDrawerOpen(o => !o)} />
      <main
        style={{
          marginLeft: isMobile ? 0 : 88,
          marginTop: 56,
          padding: isMobile ? '16px' : '24px',
          minHeight: 'calc(100vh - 56px)',
        }}
      >
        {children}
      </main>
    </div>
  )
}
