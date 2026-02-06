import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadBatch, uploadSingle } from '../lib/api.js'

function UploadCard({ title, hint, children }) {
  return (
    <section className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-5 shadow-lg shadow-blue-950/10">
      <div className="mb-2 text-lg font-semibold text-slate-100">{title}</div>
      <div className="mb-4 text-sm text-slate-400">{hint}</div>
      {children}
    </section>
  )
}

export default function Upload() {
  const [single, setSingle] = useState(null)
  const [multi, setMulti] = useState([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  async function onUploadSingle() {
    if (!single) return
    setBusy(true)
    setMsg('')
    try {
      const r = await uploadSingle(single)
      setMsg(`Uploaded capture_id=${r.capture_id}`)
      navigate('/queue')
    } catch (e) {
      setMsg(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onUploadBatch() {
    if (!multi.length) return
    setBusy(true)
    setMsg('')
    try {
      const r = await uploadBatch(multi)
      setMsg(`Uploaded batch: count=${r.count}`)
      navigate('/queue')
    } catch (e) {
      setMsg(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-blue-300/20 bg-gradient-to-r from-blue-500/15 to-cyan-400/10 p-5">
        <h1 className="text-2xl font-semibold text-slate-100">Upload</h1>
        <p className="mt-1 text-sm text-slate-300">อัปโหลดภาพเพื่อนำไปประมวลผล และตรวจผลที่หน้า Verification Queue</p>
      </div>

      {msg && <div className="rounded-xl border border-blue-300/30 bg-blue-500/10 p-3 text-sm text-blue-100">{msg}</div>}

      <UploadCard title="Single Image" hint="ส่งภาพเดี่ยวสำหรับทดสอบเร็ว">
        <input type="file" accept="image/*" onChange={(e) => setSingle(e.target.files?.[0] || null)} className="file-input" />
        <button disabled={busy || !single} onClick={onUploadSingle} className="btn-blue mt-4 disabled:opacity-50">Upload single</button>
      </UploadCard>

      <UploadCard title="Multiple Images" hint="อัปโหลดหลายภาพพร้อมกันเพื่อเข้าคิวประมวลผล">
        <input type="file" accept="image/*" multiple onChange={(e) => setMulti(Array.from(e.target.files || []))} className="file-input" />
        <button disabled={busy || !multi.length} onClick={onUploadBatch} className="btn-blue mt-4 disabled:opacity-50">
          Upload batch ({multi.length})
        </button>
      </UploadCard>
    </div>
  )
}
