import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/upload', label: 'Upload' },
  { to: '/queue', label: 'Verification' },
  { to: '/master', label: 'Master' },
  { to: '/rtsp', label: 'RTSP' },
]

function BrandIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-9 w-9" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="2" y="2" width="44" height="44" rx="14" className="fill-blue-500/20 stroke-blue-300" strokeWidth="2" />
      <path d="M14 26h20M16 19h16M18 33h12" className="stroke-blue-200" strokeWidth="3" strokeLinecap="round" />
      <circle cx="34" cy="33" r="4" className="fill-sky-400" />
    </svg>
  )
}

function NavItem({ to, label }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center rounded-xl px-3 py-2 text-sm font-medium transition ${
          isActive
            ? 'bg-blue-500/20 text-blue-100 shadow-[inset_0_0_0_1px_rgba(96,165,250,0.35)]'
            : 'text-slate-300 hover:bg-white/10 hover:text-white'
        }`
      }
    >
      {label}
    </NavLink>
  )
}

export default function AppLayout() {
  return (
    <div className="min-h-screen app-bg text-slate-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_20%_15%,rgba(59,130,246,0.28),transparent_35%),radial-gradient(circle_at_80%_0%,rgba(14,165,233,0.2),transparent_30%)]" />
      <div className="relative mx-auto grid min-h-screen max-w-7xl grid-cols-1 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="glass border-b border-white/10 p-4 lg:border-b-0 lg:border-r">
          <div className="mb-6 flex items-center gap-3">
            <BrandIcon />
            <div>
              <div className="text-lg font-semibold leading-tight text-white">Thai ALPR</div>
              <p className="text-xs text-slate-300">Blue Ops Console</p>
            </div>
          </div>
          <nav className="grid gap-1">
            {navItems.map((item) => (
              <NavItem key={item.to} to={item.to} label={item.label} />
            ))}
          </nav>
        </aside>

        <div className="flex min-h-screen flex-col">
          <header className="glass sticky top-0 z-20 border-b border-white/10 px-4 py-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-blue-200/80">Operations</p>
                <h1 className="text-base font-semibold text-white md:text-lg">License Plate Recognition Console</h1>
              </div>
              <div className="rounded-full border border-blue-200/30 bg-blue-500/10 px-3 py-1 text-xs text-blue-100">Realtime monitoring</div>
            </div>
          </header>
          <main className="flex-1 px-4 py-5 md:px-6 md:py-6">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  )
}
