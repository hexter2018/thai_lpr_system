import React, { useEffect, useState } from 'react'
import { getKPI } from '../lib/api.js'

function Card({title, value}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs text-slate-500">{title}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">{value}</div>
    </div>
  )
}

export default function Dashboard() {
  const [kpi, setKpi] = useState(null)
  const [err, setErr] = useState("")

  useEffect(() => {
    getKPI().then(setKpi).catch(e => setErr(String(e)))
  }, [])

  return (
    <div>
      <div className="mb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-slate-500">Overview KPI ของระบบ</p>
        </div>
      </div>
      {err && <div className="text-red-600 mb-3">{err}</div>}
      {!kpi && !err && <div>Loading...</div>}
      {kpi && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
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
