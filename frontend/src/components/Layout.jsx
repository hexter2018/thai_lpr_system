import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/upload', label: 'Upload' },
  { to: '/queue', label: 'Verification Queue' },
  { to: '/master', label: 'Master Data' },
  { to: '/rtsp', label: 'RTSP' },
]

export default function Layout() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-6xl px-4 pb-8 pt-5 sm:px-6 lg:px-8">
        <header className="mb-6 rounded-3xl border border-blue-200/20 bg-gradient-to-r from-blue-900/50 via-blue-700/35 to-cyan-700/25 px-5 py-4 shadow-xl shadow-blue-950/30">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-xl font-bold tracking-tight">Thai ALPR</h1>
              <p className="text-sm text-blue-100/80">Detection · OCR · Verification workspace</p>
            </div>
            <nav className="flex flex-wrap gap-2">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `rounded-full px-4 py-2 text-sm font-medium transition ${
                      isActive
                        ? 'bg-blue-500 text-white shadow-md shadow-blue-950/40'
                        : 'bg-white/5 text-slate-200 hover:bg-white/15'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        </header>

        <main>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
