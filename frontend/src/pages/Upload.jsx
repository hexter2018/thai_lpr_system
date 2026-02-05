import React, { useState } from 'react'
import { uploadSingle, uploadBatch } from '../lib/api.js'

export default function Upload() {
  const [single, setSingle] = useState(null)
  const [multi, setMulti] = useState([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function onUploadSingle() {
    if (!single) return
    setBusy(true)
    setMsg('')
    try {
      const r = await uploadSingle(single)
      setMsg(`Uploaded capture_id=${r.capture_id}`)
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
    } catch (e) {
      setMsg(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <section className="glass rounded-2xl p-5">
        <h2 className="text-2xl font-semibold text-white">Upload</h2>
        <p className="mt-1 text-sm text-slate-300">อัปโหลดภาพเพื่อนำไปประมวลผล และตรวจผลใน Verification Queue</p>
      </section>

      {msg && <div className="glass rounded-xl p-3 text-sm text-blue-50">{msg}</div>}

      <section className="glass rounded-2xl p-5">
        <div className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-blue-200">Single image</div>
        <input type="file" accept="image/*" onChange={(e) => setSingle(e.target.files?.[0] || null)} className="input" />
        <button disabled={busy || !single} onClick={onUploadSingle} className="btn-primary mt-4 disabled:opacity-50">
          Upload single
        </button>
      </section>

      <section className="glass rounded-2xl p-5">
        <div className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-blue-200">Batch upload</div>
        <input
          type="file"
          accept="image/*"
          multiple
          onChange={(e) => setMulti(Array.from(e.target.files || []))}
          className="input"
        />
        <button disabled={busy || !multi.length} onClick={onUploadBatch} className="btn-primary mt-4 disabled:opacity-50">
          Upload batch ({multi.length})
        </button>
      </section>
    </div>
  )
}
