import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'Dashboard', icon: 'chart' },
  { to: '/upload', label: 'Upload', icon: 'upload' },
  { to: '/queue', label: 'Verification', icon: 'queue' },
  { to: '/master', label: 'Master', icon: 'db' },
  { to: '/rtsp', label: 'RTSP', icon: 'cam' },
  { to: '/reports', label: 'Reports', icon: 'report' },
]

function Icon({ type }) {
  const cls = 'h-4 w-4'
  if (type === 'upload') return <svg viewBox="0 0 24 24" fill="none" className={cls}><path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
  if (type === 'queue') return <svg viewBox="0 0 24 24" fill="none" className={cls}><path d="M8 6h12M8 12h12M8 18h12M3 6h.01M3 12h.01M3 18h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
  if (type === 'db') return <svg viewBox="0 0 24 24" fill="none" className={cls}><ellipse cx="12" cy="5" rx="8" ry="3" stroke="currentColor" strokeWidth="1.8"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" stroke="currentColor" strokeWidth="1.8"/></svg>
  if (type === 'cam') return <svg viewBox="0 0 24 24" fill="none" className={cls}><rect x="3" y="6" width="13" height="12" rx="2" stroke="currentColor" strokeWidth="1.8"/><path d="m16 10 5-3v10l-5-3z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
  if (type === 'report') return <svg viewBox="0 0 24 24" fill="none" className={cls}><path d="M9 17H7A5 5 0 0 1 7 7h2m6 10h2a5 5 0 0 0 0-10h-2m-7 5h8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
  return <svg viewBox="0 0 24 24" fill="none" className={cls}><path d="M4 19h16M7 16V9m5 7V5m5 11v-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
}

export default function AppLayout() {
  return (
    <div className="app-shell min-h-screen">
      {/* Gradient background */}
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute -top-36 left-1/4 h-96 w-96 rounded-full bg-emerald-500/20 blur-3xl" />
        <div className="absolute bottom-0 right-0 h-96 w-96 rounded-full bg-teal-400/15 blur-3xl" />
        <div className="absolute top-1/2 left-0 h-72 w-72 rounded-full bg-green-400/10 blur-3xl" />
      </div>

      <div className="mx-auto max-w-7xl space-y-4 p-4 lg:space-y-5 lg:p-6">
        <header className="glass-panel px-4 py-3 md:px-5 md:py-4">
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-500 text-white shadow-lg shadow-emerald-500/30">
                  TL
                </div>
                <div>
                  <h1 className="text-lg font-semibold bg-gradient-to-r from-emerald-400 to-teal-400 bg-clip-text text-transparent">
                    Thai ALPR
                  </h1>
                  <p className="text-xs text-slate-400">Detection · OCR · Verify · Reports</p>
                </div>
              </div>
              <div className="hidden sm:block">
                <div className="rounded-full border border-emerald-300/20 bg-emerald-500/10 px-4 py-1.5">
                  <span className="text-xs font-medium text-emerald-200">Modern Operations</span>
                </div>
              </div>
            </div>

            <nav className="top-nav flex flex-wrap items-center gap-2">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : 'nav-item-idle'}`}
                >
                  <Icon type={item.icon} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </nav>
          </div>
        </header>

        <main className="glass-panel overflow-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
