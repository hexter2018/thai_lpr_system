import React, { useState, useEffect } from 'react'
import { absImageUrl } from '../lib/api.js'

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

export default function Reports() {
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [province, setProvince] = useState('')
  const [cameraId, setCameraId] = useState('')
  const [stats, setStats] = useState(null)
  const [activity, setActivity] = useState([])
  const [accuracy, setAccuracy] = useState([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    // Set default dates (last 7 days)
    const end = new Date()
    const start = new Date()
    start.setDate(start.getDate() - 7)
    setEndDate(end.toISOString().split('T')[0])
    setStartDate(start.toISOString().split('T')[0])
  }, [])

  async function fetchStats() {
    setLoading(true)
    setErr('')
    try {
      const params = new URLSearchParams()
      if (startDate) params.append('start_date', startDate)
      if (endDate) params.append('end_date', endDate)
      if (province) params.append('province', province)
      if (cameraId) params.append('camera_id', cameraId)

      const res = await fetch(`${API_BASE}/api/reports/stats?${params}`)
      if (!res.ok) throw new Error('Failed to fetch stats')
      const data = await res.json()
      setStats(data)

      const actRes = await fetch(`${API_BASE}/api/reports/activity?${params}&limit=50`)
      if (actRes.ok) {
        const actData = await actRes.json()
        setActivity(actData)
      }

      const accRes = await fetch(`${API_BASE}/api/reports/accuracy?days=7`)
      if (accRes.ok) {
        const accData = await accRes.json()
        setAccuracy(accData)
      }
    } catch (e) {
      setErr(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (startDate && endDate) {
      fetchStats()
    }
  }, [startDate, endDate, province, cameraId])

  function exportCSV() {
    const params = new URLSearchParams()
    if (startDate) params.append('start_date', startDate)
    if (endDate) params.append('end_date', endDate)
    if (province) params.append('province', province)
    if (cameraId) params.append('camera_id', cameraId)
    window.open(`${API_BASE}/api/reports/export?${params}`, '_blank')
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      <div className="rounded-2xl border border-blue-300/20 bg-gradient-to-r from-blue-600/20 to-cyan-500/10 p-5">
        <h1 className="text-2xl font-semibold text-slate-100">รายงานย้อนหลัง</h1>
        <p className="text-sm text-slate-300">ดูสถิติและข้อมูลการตรวจจับป้ายทะเบียนย้อนหลังตามช่วงเวลา</p>
      </div>

      {err && <div className="rounded-xl border border-rose-300/40 bg-rose-500/10 p-3 text-rose-200">{err}</div>}

      <div className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-5 shadow-lg">
        <h2 className="mb-4 text-lg font-semibold text-slate-100">ตัวกรอง</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <label className="text-sm text-slate-300">
            วันเริ่มต้น
            <input
              type="date"
              className="input-dark mt-1"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label className="text-sm text-slate-300">
            วันสิ้นสุด
            <input
              type="date"
              className="input-dark mt-1"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </label>
          <label className="text-sm text-slate-300">
            จังหวัด (ถ้ามี)
            <input
              type="text"
              placeholder="กรุงเทพมหานคร"
              className="input-dark mt-1"
              value={province}
              onChange={(e) => setProvince(e.target.value)}
            />
          </label>
          <label className="text-sm text-slate-300">
            Camera ID (ถ้ามี)
            <input
              type="text"
              placeholder="plaza2-lane1"
              className="input-dark mt-1"
              value={cameraId}
              onChange={(e) => setCameraId(e.target.value)}
            />
          </label>
        </div>
        <div className="mt-4 flex gap-2">
          <button onClick={fetchStats} disabled={loading} className="btn-blue">
            {loading ? 'กำลังโหลด...' : 'ค้นหา'}
          </button>
          <button onClick={exportCSV} disabled={!stats} className="btn-soft">
            📥 Export CSV
          </button>
        </div>
      </div>

      {stats && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard title="Total Reads" value={stats.total_reads} />
            <StatCard title="Verified" value={stats.verified_reads} />
            <StatCard title="ALPR (ถูกต้อง)" value={stats.alpr_total} color="emerald" />
            <StatCard title="MLPR (แก้ไข)" value={stats.mlpr_total} color="rose" />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-5 shadow-lg">
              <h2 className="mb-4 text-lg font-semibold text-slate-100">
                ความแม่นยำ: {stats.accuracy.toFixed(1)}%
              </h2>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-300">High Confidence (≥90%)</span>
                  <span className="text-emerald-400">{stats.high_confidence}</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-emerald-500"
                    style={{ width: `${(stats.high_confidence / Math.max(stats.total_reads, 1)) * 100}%` }}
                  />
                </div>

                <div className="flex justify-between text-sm">
                  <span className="text-slate-300">Medium Confidence (70-90%)</span>
                  <span className="text-amber-400">{stats.medium_confidence}</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-amber-500"
                    style={{ width: `${(stats.medium_confidence / Math.max(stats.total_reads, 1)) * 100}%` }}
                  />
                </div>

                <div className="flex justify-between text-sm">
                  <span className="text-slate-300">Low Confidence (&lt;70%)</span>
                  <span className="text-rose-400">{stats.low_confidence}</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-rose-500"
                    style={{ width: `${(stats.low_confidence / Math.max(stats.total_reads, 1)) * 100}%` }}
                  />
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-5 shadow-lg">
              <h2 className="mb-4 text-lg font-semibold text-slate-100">จังหวัดยอดนิยม Top 10</h2>
              <div className="space-y-2 text-sm">
                {stats.top_provinces.map((p, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <span className="text-slate-300">{p.province || 'ไม่ระบุ'}</span>
                    <span className="font-semibold text-blue-100">{p.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {accuracy.length > 0 && (
            <div className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-5 shadow-lg">
              <h2 className="mb-4 text-lg font-semibold text-slate-100">กราฟความแม่นยำรายวัน</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-blue-200/20">
                    <tr>
                      <th className="p-2 text-left text-slate-300">วันที่</th>
                      <th className="p-2 text-right text-slate-300">ALPR</th>
                      <th className="p-2 text-right text-slate-300">MLPR</th>
                      <th className="p-2 text-right text-slate-300">Total</th>
                      <th className="p-2 text-right text-slate-300">Accuracy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {accuracy.map((row, i) => (
                      <tr key={i} className="border-b border-slate-800">
                        <td className="p-2 text-slate-100">{row.date}</td>
                        <td className="p-2 text-right text-emerald-400">{row.alpr}</td>
                        <td className="p-2 text-right text-rose-400">{row.mlpr}</td>
                        <td className="p-2 text-right text-slate-100">{row.total}</td>
                        <td className="p-2 text-right font-semibold text-blue-100">{row.accuracy.toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-5 shadow-lg">
            <h2 className="mb-4 text-lg font-semibold text-slate-100">Activity Log (ล่าสุด 50 รายการ)</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-blue-200/20">
                  <tr>
                    <th className="p-2 text-left text-slate-300">Crop</th>
                    <th className="p-2 text-left text-slate-300">Plate</th>
                    <th className="p-2 text-left text-slate-300">Province</th>
                    <th className="p-2 text-left text-slate-300">Conf.</th>
                    <th className="p-2 text-left text-slate-300">Status</th>
                    <th className="p-2 text-left text-slate-300">Camera</th>
                    <th className="p-2 text-left text-slate-300">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {activity.map((a) => (
                    <tr key={a.id} className="border-b border-slate-800">
                      <td className="p-2">
                        <img
                          src={absImageUrl(a.crop_url)}
                          alt="crop"
                          className="h-10 w-16 rounded border border-blue-200/20 object-cover"
                        />
                      </td>
                      <td className="p-2 font-mono text-slate-100">{a.plate_text || '-'}</td>
                      <td className="p-2 text-slate-300">{a.province || '-'}</td>
                      <td className="p-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs ${
                            a.confidence >= 0.9
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : a.confidence >= 0.7
                                ? 'bg-amber-500/20 text-amber-300'
                                : 'bg-rose-500/20 text-rose-300'
                          }`}
                        >
                          {(a.confidence * 100).toFixed(0)}%
                        </span>
                      </td>
                      <td className="p-2 text-slate-300">{a.status}</td>
                      <td className="p-2 text-slate-300">{a.camera_id}</td>
                      <td className="p-2 text-slate-400">{new Date(a.created_at).toLocaleString('th-TH')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function StatCard({ title, value, color = 'blue' }) {
  const colors = {
    blue: 'border-blue-300/20 bg-slate-900/55',
    emerald: 'border-emerald-300/20 bg-emerald-500/10',
    rose: 'border-rose-300/20 bg-rose-500/10',
  }
  return (
    <div className={`rounded-2xl border p-4 shadow-lg ${colors[color]}`}>
      <div className="text-xs uppercase tracking-wide text-slate-400">{title}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  )
}
