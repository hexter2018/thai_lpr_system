import React, { useEffect, useState } from 'react'
import { getKPI } from '../lib/api.js'

function Card({title, value}) {
  return (
    <div className="border rounded p-4">
      <div className="text-xs text-gray-500">{title}</div>
      <div className="text-2xl font-semibold">{value}</div>
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
      <h1 className="text-xl font-bold mb-3">Dashboard KPI</h1>
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
