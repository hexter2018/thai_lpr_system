import React from 'react'
import { NavLink, Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard.jsx'
import Upload from './pages/Upload.jsx'
import Queue from './pages/Queue.jsx'
import Master from './pages/Master.jsx'
import Rtsp from './pages/Rtsp.jsx'

function NavItem({to, children}) {
  return (
    <NavLink
      to={to}
      className={({isActive}) =>
        "px-3 py-2 rounded-xl text-sm font-medium transition " +
        (isActive
          ? "bg-blue-600 text-white shadow-sm"
          : "text-slate-700 hover:bg-slate-100")
      }
    >
      {children}
    </NavLink>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-sky-50/60 via-slate-50 to-slate-100/40">
      <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/85 backdrop-blur">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-2xl bg-gradient-to-br from-blue-600 to-sky-400 shadow-md shadow-blue-200" />
            <div>
              <div className="font-bold leading-tight">Thai ALPR</div>
              <div className="text-xs text-slate-500">Plate detection • OCR • Verification</div>
            </div>
          </div>

          <nav className="hidden md:flex items-center gap-2">
            <NavItem to="/">Dashboard</NavItem>
            <NavItem to="/upload">Upload</NavItem>
            <NavItem to="/queue">Verification</NavItem>
            <NavItem to="/master">Master</NavItem>
            <NavItem to="/rtsp">RTSP</NavItem>
          </nav>
        </div>

        {/* Mobile nav */}
        <div className="md:hidden px-4 pb-3">
          <div className="flex flex-wrap gap-2">
            <NavItem to="/">Dashboard</NavItem>
            <NavItem to="/upload">Upload</NavItem>
            <NavItem to="/queue">Verification</NavItem>
            <NavItem to="/master">Master</NavItem>
            <NavItem to="/rtsp">RTSP</NavItem>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto p-4 md:p-5">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/master" element={<Master />} />
          <Route path="/rtsp" element={<Rtsp />} />
        </Routes>
      </main>
    </div>
  )
}
