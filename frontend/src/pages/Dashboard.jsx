import React, { useEffect, useState } from 'react'
import { getKPI } from '../lib/api.js'
import { Card, CardBody, CardHeader, StatCard, Spinner, Badge } from '../components/UIComponents.jsx'
// แนะนำ: หากคุณมี Lucide-React ให้ใช้ Icon เหล่านี้แทนจะสวยมากครับ
// import { Activity, ShieldCheck, Users, Target } from 'lucide-react'

/* ===== MODERN ACCURACY GAUGE (Updated) ===== */
function AccuracyGauge({ percentage }) {
  const radius = 70
  const stroke = 12
  const normalizedRadius = radius - stroke / 2
  const circumference = normalizedRadius * 2 * Math.PI
  const strokeDashoffset = circumference - (percentage / 100) * circumference

  return (
    <div className="relative flex items-center justify-center">
      <svg height={radius * 2} width={radius * 2} className="transform -rotate-90">
        <circle
          stroke="currentColor"
          fill="transparent"
          strokeWidth={stroke}
          className="text-slate-200 dark:text-slate-800"
          r={normalizedRadius}
          cx={radius}
          cy={radius}
        />
        <circle
          stroke="currentColor"
          fill="transparent"
          strokeWidth={stroke}
          strokeDasharray={circumference + ' ' + circumference}
          style={{ strokeDashoffset }}
          strokeLinecap="round"
          className="text-emerald-500 transition-all duration-1000 ease-out"
          r={normalizedRadius}
          cx={radius}
          cy={radius}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold dark:text-white">{percentage}%</span>
        <span className="text-[10px] uppercase tracking-wider text-slate-400">System Accuracy</span>
      </div>
    </div>
  )
}

const Dashboard = () => {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchKPI = async () => {
      try {
        const res = await getKPI()
        setData(res.data)
      } catch (err) {
        console.error('Failed to fetch KPI:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchKPI()
    const interval = setInterval(fetchKPI, 30000) // Refresh ทุก 30 วินาที
    return () => clearInterval(interval)
  }, [])

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-page-light dark:bg-page-dark">
      <Spinner size="xl" />
    </div>
  )

  return (
    <div className="min-h-screen p-6 transition-colors duration-500 bg-page-light dark:bg-page-dark text-slate-900 dark:text-slate-100">
      
      {/* 🚀 Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-blue-600 to-emerald-500 bg-clip-text text-transparent">
            LPR Overview
          </h1>
          <p className="text-slate-500 dark:text-slate-400 font-medium">Monitoring activity across all zones</p>
        </div>
        <div className="flex items-center gap-2 px-4 py-2 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700">
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-sm font-semibold">Live System Active</span>
        </div>
      </div>

      {/* 📊 KPI Cards Section */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard 
          title="Total Detected" 
          value={data?.total?.toLocaleString() || '0'} 
          trend="+12% from yesterday"
          className="dark:bg-slate-800/50 dark:border-slate-700"
        />
        <StatCard 
          title="Members" 
          value={data?.members?.toLocaleString() || '0'} 
          className="dark:bg-slate-800/50 dark:border-slate-700 text-emerald-500"
        />
        <StatCard 
          title="Visitors" 
          value={data?.visitors?.toLocaleString() || '0'} 
          className="dark:bg-slate-800/50 dark:border-slate-700 text-amber-500"
        />
        <StatCard 
          title="Unknown / Blacklist" 
          value={data?.blacklist || '0'} 
          className="dark:bg-slate-800/50 dark:border-slate-700 text-rose-500"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* 🎯 Accuracy & Performance (Left) */}
        <Card className="dark:bg-slate-800/50 dark:border-slate-700 backdrop-blur-md">
          <CardHeader>
            <h3 className="text-lg font-bold">System Health</h3>
          </CardHeader>
          <CardBody className="flex flex-col items-center py-8">
            <AccuracyGauge percentage={98} />
            <div className="w-full mt-8 space-y-4">
              <div className="flex justify-between items-center text-sm">
                <span className="text-slate-500">Processing Speed</span>
                <span className="font-mono font-bold text-emerald-400">0.42s / frame</span>
              </div>
              <div className="h-1.5 w-full bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                <div className="h-full bg-emerald-500 w-[92%]" />
              </div>
            </div>
          </CardBody>
        </Card>

        {/* 🚗 Recent Activity (Right/Middle) */}
        <Card className="lg:col-span-2 dark:bg-slate-800/50 dark:border-slate-700 backdrop-blur-md">
          <CardHeader className="flex justify-between items-center">
            <h3 className="text-lg font-bold">Recent Recognition Logs</h3>
            <button className="text-xs text-blue-500 font-semibold hover:underline">View All Reports</button>
          </CardHeader>
          <CardBody>
            <div className="space-y-3">
              {/* ตัวอย่างรายการข้อมูล */}
              {[1, 2, 3, 4, 5].map((item) => (
                <div key={item} className="group flex items-center justify-between p-3 rounded-xl border border-transparent hover:border-slate-200 dark:hover:border-slate-700 hover:bg-white dark:hover:bg-slate-800 transition-all duration-200">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-lg bg-slate-100 dark:bg-slate-900 flex items-center justify-center font-bold text-[10px] text-slate-400 group-hover:text-blue-500">IMG</div>
                    <div>
                      <div className="text-sm font-bold tracking-wide">1กก 9999 กรุงเทพฯ</div>
                      <div className="text-[10px] text-slate-500">Entrance A • Today, 14:2{item}</div>
                    </div>
                  </div>
                  <Badge variant={item % 2 === 0 ? 'success' : 'warning'}>
                    {item % 2 === 0 ? 'Member' : 'Visitor'}
                  </Badge>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>

      </div>
    </div>
  )
}

export default Dashboard