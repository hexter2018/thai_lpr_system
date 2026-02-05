import React, { useEffect, useState } from 'react'
import { getKPI } from '../lib/api.js'

function KpiCard({ title, value }) {
  return (
    <div className="glass rounded-2xl p-4">
      <div className="text-xs uppercase tracking-[0.14em] text-blue-200/75">{title}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
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
      <section className="glass rounded-2xl p-5">
        <h2 className="text-2xl font-semibold text-white">Dashboard</h2>
        <p className="mt-1 text-sm text-slate-300">Overview KPI ของระบบ Thai ALPR</p>
      </section>

      {err && <div className="rounded-xl border border-rose-300/30 bg-rose-500/10 p-3 text-rose-100">{err}</div>}
      {!kpi && !err && <div className="text-sm text-slate-300">Loading KPI...</div>}

      {kpi && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <KpiCard title="Total reads" value={kpi.total_reads} />
          <KpiCard title="Pending queue" value={kpi.pending} />
          <KpiCard title="Verified" value={kpi.verified} />
          <KpiCard title="Auto-master" value={kpi.auto_master} />
          <KpiCard title="Master total" value={kpi.master_total} />
          <KpiCard title="ALPR (confirmed)" value={kpi.alpr_total} />
          <KpiCard title="MLPR (corrected)" value={kpi.mlpr_total} />
        </div>
      )}
    </div>
  )
}
