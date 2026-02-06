import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Upload from './pages/Upload.jsx'
import Queue from './pages/Queue.jsx'
import Master from './pages/Master.jsx'
import Rtsp from './pages/Rtsp.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/queue" element={<Queue />} />
        <Route path="/master" element={<Master />} />
        <Route path="/rtsp" element={<Rtsp />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
