import React, { useEffect, useState } from 'react'
import { getKPI } from '../lib/api.js'
import { Card, PageHeader } from '../components/ui.jsx'

export default function Dashboard() {
  const [kpi, setKpi] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    getKPI().then(setKpi).catch((e) => setErr(String(e)))
  }, [])

  const stats = kpi ? [
    ['Total reads', kpi.total_reads],
    ['Pending queue', kpi.pending],
    ['Verified', kpi.verified],
    ['Auto-master (conf ≥ 0.95)', kpi.auto_master],
    ['Master total', kpi.master_total],
    ['ALPR (confirmed)', kpi.alpr_total],
    ['MLPR (corrected)', kpi.mlpr_total],
  ] : []

  return (
    <div>
      <PageHeader title="Dashboard" subtitle="ภาพรวม KPI ของระบบตรวจป้ายทะเบียน" />
      {err && <Card className="mb-4 border-rose-300/30 text-rose-200">{err}</Card>}
      {!kpi && !err && <Card>Loading...</Card>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map(([title, value]) => (
          <Card key={title}>
            <div className="text-xs text-slate-400">{title}</div>
            <div className="mt-1 text-3xl font-semibold tracking-tight">{value}</div>
          </Card>
        ))}
      </div>
    </div>
  )
}
