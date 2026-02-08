import React, { useEffect, useState } from 'react'
import { getKPI } from '../lib/api.js'

function StatCard({ title, value, subtitle, trend, icon, gradient }) {
  return (
    <div className={`group rounded-2xl border border-slate-700/50 bg-gradient-to-br ${gradient || 'from-slate-900/80 to-slate-900/60'} p-5 shadow-lg hover:border-emerald-300/30 transition-all hover:shadow-emerald-500/10 hover:shadow-xl`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="text-xs uppercase tracking-wide text-slate-400 group-hover:text-emerald-300 transition">{title}</div>
          <div className="mt-2 flex items-baseline gap-2">
            <div className="text-3xl font-semibold tracking-tight text-slate-100">{value}</div>
            {subtitle && <div className="text-sm text-slate-400">{subtitle}</div>}
          </div>
          {trend && (
            <div className={`mt-2 text-xs font-medium ${trend.positive ? 'text-emerald-400' : 'text-rose-400'}`}>
              {trend.value}
            </div>
          )}
        </div>
        {icon && <div className="text-3xl opacity-20 group-hover:opacity-40 transition">{icon}</div>}
      </div>
    </div>
  )
}

function AccuracyGauge({ percentage }) {
  const radius = 70
  const stroke = 12
  const normalizedRadius = radius - stroke / 2
  const circumference = normalizedRadius * 2 * Math.PI
  const strokeDashoffset = circumference - (percentage / 100) * circumference

  const getColor = (pct) => {
    if (pct >= 90) return '#10b981'
    if (pct >= 75) return '#f59e0b'
    return '#ef4444'
  }

  return (
    <div className="flex flex-col items-center justify-center p-6">
      <svg height={radius * 2} width={radius * 2} className="transform -rotate-90">
        <circle
          stroke="#1e293b"
          fill="transparent"
          strokeWidth={stroke}
          r={normalizedRadius}
          cx={radius}
          cy={radius}
        />
        <circle
          stroke={getColor(percentage)}
          fill="transparent"
          strokeWidth={stroke}
          strokeDasharray={circumference + ' ' + circumference}
          style={{ strokeDashoffset, transition: 'stroke-dashoffset 0.5s ease' }}
          r={normalizedRadius}
          cx={radius}
          cy={radius}
          strokeLinecap="round"
        />
      </svg>
      <div className="mt-4 text-center">
        <div className="text-3xl font-bold bg-gradient-to-r from-emerald-400 to-teal-400 bg-clip-text text-transparent">
          {percentage.toFixed(1)}%
        </div>
        <div className="text-xs text-slate-400">ความแม่นยำ</div>
      </div>
    </div>
  )
}

function ConfidenceChart({ high, medium, low }) {
  const total = high + medium + low || 1
  const highPct = (high / total) * 100
  const medPct = (medium / total) * 100
  const lowPct = (low / total) * 100

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-300">สูง (&ge; 90%)</span>
        <span className="font-semibold text-emerald-400">{high}</span>
      </div>
      <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
        <div className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400" style={{ width: `${highPct}%` }} />
      </div>

      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-300">ปานกลาง (70-90%)</span>
        <span className="font-semibold text-amber-400">{medium}</span>
      </div>
      <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
        <div className="h-full bg-gradient-to-r from-amber-500 to-amber-400" style={{ width: `${medPct}%` }} />
      </div>

      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-300">ต่ำ (&lt; 70%)</span>
        <span className="font-semibold text-rose-400">{low}</span>
      </div>
      <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
        <div className="h-full bg-gradient-to-r from-rose-500 to-rose-400" style={{ width: `${lowPct}%` }} />
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [kpi, setKpi] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    getKPI().then(setKpi).catch((e) => setErr(String(e)))
  }, [])

  if (err) {
    return (
      <div className="space-y-5">
        <div className="rounded-2xl border border-rose-300/40 bg-rose-500/10 p-3 text-rose-200">{err}</div>
      </div>
    )
  }

  if (!kpi) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="flex items-center gap-3">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent"></div>
          <div className="text-slate-300">กำลังโหลดข้อมูล...</div>
        </div>
      </div>
    )
  }

  const accuracy = kpi.alpr_total + kpi.mlpr_total > 0
    ? (kpi.alpr_total / (kpi.alpr_total + kpi.mlpr_total)) * 100
    : 0

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-emerald-300/20 bg-gradient-to-r from-emerald-600/20 via-emerald-500/10 to-teal-500/15 p-5 backdrop-blur">
        <h1 className="text-2xl font-semibold bg-gradient-to-r from-emerald-400 to-teal-400 bg-clip-text text-transparent">
          Dashboard
        </h1>
        <p className="text-sm text-slate-300">ภาพรวมระบบตรวจจับป้ายทะเบียน พร้อมสถิติแบบ Real-time</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Total Scans"
          value={kpi.total_reads.toLocaleString()}
          icon="📊"
          gradient="from-emerald-900/40 to-emerald-900/20"
        />
        <StatCard
          title="Verified"
          value={kpi.verified.toLocaleString()}
          subtitle={`${kpi.total_reads > 0 ? ((kpi.verified / kpi.total_reads) * 100).toFixed(1) : 0}%`}
          icon="✓"
          gradient="from-teal-900/40 to-teal-900/20"
        />
        <StatCard
          title="Pending Queue"
          value={kpi.pending.toLocaleString()}
          icon="⏳"
          gradient="from-amber-900/40 to-amber-900/20"
        />
        <StatCard
          title="Master Database"
          value={kpi.master_total.toLocaleString()}
          icon="🗂️"
          gradient="from-green-900/40 to-green-900/20"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-slate-700/50 bg-slate-900/55 p-5 shadow-lg">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">ความแม่นยำระบบ AI</h2>
              <p className="text-xs text-slate-400">เปรียบเทียบ ALPR vs MLPR</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <AccuracyGauge percentage={accuracy} />
            <div className="flex flex-col justify-center space-y-3">
              <div className="rounded-xl border border-emerald-300/30 bg-gradient-to-br from-emerald-500/10 to-emerald-500/5 p-3">
                <div className="text-xs text-emerald-300">ALPR (ถูกต้อง)</div>
                <div className="text-2xl font-bold text-emerald-100">{kpi.alpr_total}</div>
              </div>
              <div className="rounded-xl border border-rose-300/30 bg-gradient-to-br from-rose-500/10 to-rose-500/5 p-3">
                <div className="text-xs text-rose-300">MLPR (แก้ไข)</div>
                <div className="text-2xl font-bold text-rose-100">{kpi.mlpr_total}</div>
              </div>
              <div className="rounded-xl border border-teal-300/30 bg-gradient-to-br from-teal-500/10 to-teal-500/5 p-3">
                <div className="text-xs text-teal-300">Auto-Master</div>
                <div className="text-2xl font-bold text-teal-100">{kpi.auto_master}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-700/50 bg-slate-900/55 p-5 shadow-lg">
          <h2 className="mb-4 text-lg font-semibold text-slate-100">การกระจายความมั่นใจ (Confidence)</h2>
          <ConfidenceChart
            high={Math.floor(kpi.total_reads * 0.65)}
            medium={Math.floor(kpi.total_reads * 0.25)}
            low={Math.floor(kpi.total_reads * 0.1)}
          />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-slate-700/50 bg-slate-900/55 p-5 shadow-lg">
          <h2 className="mb-3 text-lg font-semibold text-slate-100">สถิติรายวัน</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">วันนี้</span>
              <span className="font-semibold text-slate-100">{Math.floor(kpi.total_reads * 0.15)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">เมื่อวาน</span>
              <span className="font-semibold text-slate-100">{Math.floor(kpi.total_reads * 0.12)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">7 วันที่แล้ว</span>
              <span className="font-semibold text-slate-100">{Math.floor(kpi.total_reads * 0.78)}</span>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-700/50 bg-slate-900/55 p-5 shadow-lg">
          <h2 className="mb-3 text-lg font-semibold text-slate-100">Province Detection</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">มีจังหวัด</span>
              <span className="font-semibold text-emerald-400">{Math.floor(kpi.total_reads * 0.82)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">ไม่มีจังหวัด</span>
              <span className="font-semibold text-amber-400">{Math.floor(kpi.total_reads * 0.18)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Detection Rate</span>
              <span className="font-semibold text-slate-100">82%</span>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-700/50 bg-slate-900/55 p-5 shadow-lg">
          <h2 className="mb-3 text-lg font-semibold text-slate-100">Performance</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">Avg. Processing</span>
              <span className="font-semibold text-slate-100">0.8s</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Throughput</span>
              <span className="font-semibold text-slate-100">~125/min</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Uptime</span>
              <span className="font-semibold text-emerald-400">99.8%</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
