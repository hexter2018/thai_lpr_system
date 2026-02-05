import React from 'react'
import { NavLink, Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard.jsx'
import Upload from './pages/Upload.jsx'
import Queue from './pages/Queue.jsx'
import Master from './pages/Master.jsx'

function NavItem({to, children}) {
  return (
    <NavLink
      to={to}
      className={({isActive}) =>
        "px-3 py-2 rounded " + (isActive ? "bg-black text-white" : "hover:bg-gray-100")
      }
    >
      {children}
    </NavLink>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-white">
      <header className="border-b">
        <div className="max-w-6xl mx-auto p-4 flex items-center gap-3">
          <div className="font-bold text-lg">Thai ALPR</div>
          <nav className="flex gap-2 text-sm">
            <NavItem to="/">Dashboard</NavItem>
            <NavItem to="/upload">Upload</NavItem>
            <NavItem to="/queue">Verification Queue</NavItem>
            <NavItem to="/master">Master Data</NavItem>
          </nav>
        </div>
      </header>

      <main className="max-w-6xl mx-auto p-4">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/master" element={<Master />} />
        </Routes>
      </main>
    </div>
  )
}
