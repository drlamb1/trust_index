import type { ReactNode } from 'react'
import Sidebar from './Sidebar'
import TopBar from './TopBar'

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div style={{ minHeight: '100vh' }}>
      <Sidebar />
      <TopBar />
      <main
        style={{
          marginLeft: 72,
          marginTop: 56,
          padding: '24px',
          minHeight: 'calc(100vh - 56px)',
        }}
      >
        {children}
      </main>
    </div>
  )
}
