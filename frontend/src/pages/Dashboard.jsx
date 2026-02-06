import React, { useEffect, useState } from 'react'
import { getKPI } from '../lib/api.js'

function Card({ title, value }) {
  return (
    <div className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-4 shadow-lg shadow-blue-950/20">
      <div className="text-xs text-slate-400">{title}</div>
      <div className="mt-1 text-3xl font-semibold tracking-tight text-slate-100">{value}</div>
    </div>
  )
}

export default function Dashboard() {
  const [kpi, setKpi] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    getKPI().then(setKpi).catch((e) => setErr(String(e)))
  }, [])

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-blue-300/20 bg-gradient-to-r from-blue-600/20 to-cyan-500/10 p-5">
        <h1 className="text-2xl font-semibold text-slate-100">Dashboard</h1>
        <p className="text-sm text-slate-300">Overview KPI ของระบบตรวจป้ายทะเบียน</p>
      </div>

      {err && <div className="rounded-xl border border-rose-400/30 bg-rose-500/10 p-3 text-rose-200">{err}</div>}
      {!kpi && !err && <div className="text-slate-300">Loading...</div>}

      {kpi && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Card title="Total reads" value={kpi.total_reads} />
          <Card title="Pending queue" value={kpi.pending} />
          <Card title="Verified" value={kpi.verified} />
          <Card title="Auto-master (conf ≥ 0.95)" value={kpi.auto_master} />
          <Card title="Master total" value={kpi.master_total} />
          <Card title="ALPR (confirmed)" value={kpi.alpr_total} />
          <Card title="MLPR (corrected)" value={kpi.mlpr_total} />
        </div>
      )}
    </div>
  )
}
