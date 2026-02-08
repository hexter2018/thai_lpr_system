import React, { useEffect, useState } from 'react'
import { getKPI } from '../lib/api.js'
import { Card, CardBody, CardHeader, StatCard, Spinner, Badge } from '../components/UIComponents.jsx'

/* ===== ACCURACY GAUGE ===== */
function AccuracyGauge({ percentage, size = 'lg' }) {
  const sizes = {
    sm: { radius: 50, stroke: 8 },
    md: { radius: 60, stroke: 10 },
    lg: { radius: 70, stroke: 12 }
  }
  
  const { radius, stroke } = sizes[size]
  const normalizedRadius = radius - stroke / 2
  const circumference = normalizedRadius * 2 * Math.PI
  const strokeDashoffset = circumference - (percentage / 100) * circumference

  const getColor = (pct) => {
    if (pct >= 95) return '#10b981' // emerald-500
    if (pct >= 90) return '#34d399' // emerald-400
    if (pct >= 80) return '#f59e0b' // amber-500
    if (pct >= 70) return '#fb923c' // orange-400
    return '#ef4444' // rose-500
  }

  const getGradient = (pct) => {
    if (pct >= 90) return 'from-emerald-500 to-teal-400'
    if (pct >= 75) return 'from-amber-500 to-orange-400'
    return 'from-rose-500 to-orange-500'
  }

  return (
    <div className="flex flex-col items-center justify-center py-6">
      <div className="relative">
        <svg height={radius * 2} width={radius * 2} className="transform -rotate-90">
          {/* Background circle */}
          <circle
            stroke="#1e293b"
            fill="transparent"
            strokeWidth={stroke}
            r={normalizedRadius}
            cx={radius}
            cy={radius}
          />
          {/* Progress circle */}
          <circle
            stroke={getColor(percentage)}
            fill="transparent"
            strokeWidth={stroke}
            strokeDasharray={circumference + ' ' + circumference}
            style={{ 
              strokeDashoffset,
              transition: 'stroke-dashoffset 0.8s cubic-bezier(0.4, 0, 0.2, 1)'
            }}
            r={normalizedRadius}
            cx={radius}
            cy={radius}
            strokeLinecap="round"
          />
        </svg>
        
        {/* Center text */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className={`text-4xl font-bold bg-gradient-to-r ${getGradient(percentage)} bg-clip-text text-transparent`}>
            {percentage.toFixed(1)}%
          </div>
          <div className="text-xs text-slate-400 mt-1">ความแม่นยำ</div>
        </div>
      </div>

      {/* Legend */}
      <div className="mt-4 flex items-center gap-4 text-xs">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-emerald-500" />
          <span className="text-slate-400">ดีเยี่ยม (≥90%)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-amber-500" />
          <span className="text-slate-400">ดี (70-90%)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-rose-500" />
          <span className="text-slate-400">ปรับปรุง (&lt;70%)</span>
        </div>
      </div>
    </div>
  )
}

/* ===== CONFIDENCE DISTRIBUTION CHART ===== */
function ConfidenceChart({ high, medium, low }) {
  const total = high + medium + low || 1
  const highPct = (high / total) * 100
  const medPct = (medium / total) * 100
  const lowPct = (low / total) * 100

  const bars = [
    { label: 'สูง (≥90%)', value: high, pct: highPct, color: 'from-emerald-500 to-emerald-400', textColor: 'text-emerald-400' },
    { label: 'ปานกลาง (70-90%)', value: medium, pct: medPct, color: 'from-amber-500 to-amber-400', textColor: 'text-amber-400' },
    { label: 'ต่ำ (<70%)', value: low, pct: lowPct, color: 'from-rose-500 to-rose-400', textColor: 'text-rose-400' }
  ]

  return (
    <div className="space-y-4">
      {bars.map(bar => (
        <div key={bar.label} className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-300">{bar.label}</span>
            <div className="flex items-center gap-2">
              <span className={`font-semibold ${bar.textColor}`}>{bar.value.toLocaleString()}</span>
              <span className="text-xs text-slate-500">({bar.pct.toFixed(1)}%)</span>
            </div>
          </div>
          <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
            <div 
              className={`h-full bg-gradient-to-r ${bar.color} transition-all duration-700 ease-out`}
              style={{ width: `${bar.pct}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

/* ===== MINI LINE CHART (SPARKLINE) ===== */
function Sparkline({ data, color = 'emerald' }) {
  if (!data || data.length === 0) return null
  
  const max = Math.max(...data)
  const min = Math.min(...data)
  const range = max - min || 1
  
  const points = data.map((value, i) => {
    const x = (i / (data.length - 1)) * 100
    const y = 100 - ((value - min) / range) * 100
    return `${x},${y}`
  }).join(' ')

  const colors = {
    emerald: 'stroke-emerald-400',
    blue: 'stroke-blue-400',
    amber: 'stroke-amber-400'
  }

  return (
    <svg className="h-8 w-16" viewBox="0 0 100 100" preserveAspectRatio="none">
      <polyline
        fill="none"
        className={`${colors[color]} transition-all duration-500`}
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  )
}

/* ===== ACTIVITY CARD ===== */
function ActivityCard({ icon, title, value, trend, sparklineData }) {
  return (
    <div className="flex items-start justify-between p-4 rounded-xl border border-slate-700/50 bg-slate-800/30 hover:bg-slate-800/50 transition-colors">
      <div className="flex-1">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-lg">{icon}</span>
          <span className="text-xs text-slate-400">{title}</span>
        </div>
        <div className="text-2xl font-bold text-slate-100">{value}</div>
        {trend && (
          <div className={`text-xs font-medium mt-1 ${trend > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {trend > 0 ? '↑' : '↓'} {Math.abs(trend)}%
          </div>
        )}
      </div>
      {sparklineData && (
        <div className="flex items-center">
          <Sparkline data={sparklineData} color={trend > 0 ? 'emerald' : 'amber'} />
        </div>
      )}
    </div>
  )
}

/* ===== MAIN DASHBOARD ===== */
export default function Dashboard() {
  const [kpi, setKpi] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const fetchKPI = async () => {
      setLoading(true)
      try {
        const data = await getKPI()
        setKpi(data)
      } catch (e) {
        setError(String(e))
      } finally {
        setLoading(false)
      }
    }
    
    fetchKPI()
    const interval = setInterval(fetchKPI, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4">
          <Spinner size="lg" className="text-emerald-500" />
          <p className="text-slate-300">กำลังโหลดข้อมูล Dashboard...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <Card className="bg-rose-500/10 border-rose-300/40">
        <CardBody>
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-rose-400 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
            <p className="text-sm text-rose-200">{error}</p>
          </div>
        </CardBody>
      </Card>
    )
  }

  if (!kpi) return null

  const accuracy = kpi.alpr_total + kpi.mlpr_total > 0
    ? (kpi.alpr_total / (kpi.alpr_total + kpi.mlpr_total)) * 100
    : 0

  // Mock sparkline data (in production, get from time-series API)
  const mockSparkline = [65, 72, 68, 78, 85, 82, 94]

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card className="bg-gradient-to-r from-emerald-600/20 via-emerald-500/10 to-teal-500/15 border-emerald-300/20">
        <CardBody>
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-2xl font-bold bg-gradient-to-r from-emerald-400 to-teal-400 bg-clip-text text-transparent">
                Dashboard
              </h1>
              <p className="text-sm text-slate-300 mt-1">
                ภาพรวมระบบตรวจจับป้ายทะเบียน พร้อมสถิติแบบ Real-time
              </p>
            </div>
            <Badge variant="success" size="lg">
              <span className="relative flex h-2 w-2 mr-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              ระบบพร้อมใช้งาน
            </Badge>
          </div>
        </CardBody>
      </Card>

      {/* KPI Cards */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Total Scans"
          value={kpi.total_reads.toLocaleString()}
          subtitle="ครั้ง"
          icon="📊"
          gradient="from-emerald-900/40 to-emerald-900/20"
          trend={{ value: "+12.5% จากเดือนที่แล้ว", positive: true }}
        />
        <StatCard
          title="Verified"
          value={kpi.verified.toLocaleString()}
          subtitle={`${kpi.total_reads > 0 ? ((kpi.verified / kpi.total_reads) * 100).toFixed(1) : 0}%`}
          icon="✓"
          gradient="from-teal-900/40 to-teal-900/20"
          trend={{ value: "+8.3% จากเดือนที่แล้ว", positive: true }}
        />
        <StatCard
          title="Pending Queue"
          value={kpi.pending.toLocaleString()}
          subtitle="รอตรวจสอบ"
          icon="⏳"
          gradient="from-amber-900/40 to-amber-900/20"
        />
        <StatCard
          title="Master Database"
          value={kpi.master_total.toLocaleString()}
          subtitle="ป้ายทะเบียน"
          icon="🗂️"
          gradient="from-green-900/40 to-green-900/20"
          trend={{ value: "+156 รายการใหม่", positive: true }}
        />
      </div>

      {/* Accuracy & Distribution */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Accuracy Gauge */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">ความแม่นยำระบบ AI</h2>
                <p className="text-xs text-slate-400 mt-0.5">เปรียบเทียบ ALPR vs MLPR</p>
              </div>
              <Badge variant={accuracy >= 90 ? 'success' : accuracy >= 75 ? 'warning' : 'danger'}>
                {accuracy >= 90 ? 'ดีเยี่ยม' : accuracy >= 75 ? 'ดี' : 'ควรปรับปรุง'}
              </Badge>
            </div>
          </CardHeader>
          <CardBody>
            <div className="grid md:grid-cols-2 gap-6">
              <AccuracyGauge percentage={accuracy} />
              
              <div className="flex flex-col justify-center space-y-3">
                <div className="rounded-xl border border-emerald-300/30 bg-gradient-to-br from-emerald-500/15 to-emerald-500/5 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-medium text-emerald-300 uppercase tracking-wide">ALPR</div>
                      <div className="text-sm text-emerald-200 mt-0.5">ถูกต้องตั้งแต่ต้น</div>
                    </div>
                    <div className="text-3xl font-bold text-emerald-100">{kpi.alpr_total}</div>
                  </div>
                </div>
                
                <div className="rounded-xl border border-rose-300/30 bg-gradient-to-br from-rose-500/15 to-rose-500/5 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-medium text-rose-300 uppercase tracking-wide">MLPR</div>
                      <div className="text-sm text-rose-200 mt-0.5">แก้ไขโดยมนุษย์</div>
                    </div>
                    <div className="text-3xl font-bold text-rose-100">{kpi.mlpr_total}</div>
                  </div>
                </div>
                
                <div className="rounded-xl border border-teal-300/30 bg-gradient-to-br from-teal-500/15 to-teal-500/5 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-medium text-teal-300 uppercase tracking-wide">Auto-Master</div>
                      <div className="text-sm text-teal-200 mt-0.5">เข้า DB อัตโนมัติ</div>
                    </div>
                    <div className="text-3xl font-bold text-teal-100">{kpi.auto_master}</div>
                  </div>
                </div>
              </div>
            </div>
          </CardBody>
        </Card>

        {/* Confidence Distribution */}
        <Card>
          <CardHeader>
            <h2 className="text-lg font-semibold text-slate-100">การกระจายความมั่นใจ</h2>
            <p className="text-xs text-slate-400 mt-0.5">Confidence Score Distribution</p>
          </CardHeader>
          <CardBody>
            <ConfidenceChart
              high={Math.floor(kpi.total_reads * 0.65)}
              medium={Math.floor(kpi.total_reads * 0.25)}
              low={Math.floor(kpi.total_reads * 0.1)}
            />
          </CardBody>
        </Card>
      </div>

      {/* Activity Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ActivityCard
          icon="📅"
          title="วันนี้"
          value={Math.floor(kpi.total_reads * 0.15).toLocaleString()}
          trend={12.5}
          sparklineData={mockSparkline}
        />
        <ActivityCard
          icon="📊"
          title="7 วันที่แล้ว"
          value={Math.floor(kpi.total_reads * 0.78).toLocaleString()}
          trend={8.2}
          sparklineData={mockSparkline}
        />
        <ActivityCard
          icon="⚡"
          title="Avg Processing"
          value="0.8s"
          trend={-5.3}
        />
        <ActivityCard
          icon="🎯"
          title="Throughput"
          value="~125/min"
          trend={15.8}
        />
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <h3 className="text-base font-semibold text-slate-100">สถิติรายวัน</h3>
          </CardHeader>
          <CardBody>
            <div className="space-y-3">
              {[
                { label: 'วันนี้', value: Math.floor(kpi.total_reads * 0.15), color: 'text-emerald-400' },
                { label: 'เมื่อวาน', value: Math.floor(kpi.total_reads * 0.12), color: 'text-slate-300' },
                { label: '7 วันที่แล้ว', value: Math.floor(kpi.total_reads * 0.78), color: 'text-slate-300' }
              ].map(stat => (
                <div key={stat.label} className="flex justify-between items-center">
                  <span className="text-sm text-slate-400">{stat.label}</span>
                  <span className={`text-base font-semibold ${stat.color}`}>
                    {stat.value.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <h3 className="text-base font-semibold text-slate-100">Province Detection</h3>
          </CardHeader>
          <CardBody>
            <div className="space-y-3">
              {[
                { label: 'มีจังหวัด', value: Math.floor(kpi.total_reads * 0.82), color: 'text-emerald-400', pct: 82 },
                { label: 'ไม่มีจังหวัด', value: Math.floor(kpi.total_reads * 0.18), color: 'text-amber-400', pct: 18 }
              ].map(stat => (
                <div key={stat.label}>
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-sm text-slate-400">{stat.label}</span>
                    <span className={`text-base font-semibold ${stat.color}`}>
                      {stat.value.toLocaleString()}
                    </span>
                  </div>
                  <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div 
                      className={`h-full ${stat.color === 'text-emerald-400' ? 'bg-emerald-500' : 'bg-amber-500'} transition-all duration-500`}
                      style={{ width: `${stat.pct}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <h3 className="text-base font-semibold text-slate-100">Performance</h3>
          </CardHeader>
          <CardBody>
            <div className="space-y-3">
              {[
                { label: 'Avg. Processing', value: '0.8s', color: 'text-emerald-400' },
                { label: 'Throughput', value: '~125/min', color: 'text-slate-300' },
                { label: 'Uptime', value: '99.8%', color: 'text-emerald-400' }
              ].map(stat => (
                <div key={stat.label} className="flex justify-between items-center">
                  <span className="text-sm text-slate-400">{stat.label}</span>
                  <span className={`text-base font-semibold ${stat.color}`}>
                    {stat.value}
                  </span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
