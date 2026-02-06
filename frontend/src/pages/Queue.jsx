import React, { useEffect, useState } from 'react'
import { absImageUrl, deleteRead, listPending, verifyRead } from '../lib/api.js'

function confidenceClass(v) {
  if (v >= 0.95) return 'text-emerald-200 border-emerald-300/40 bg-emerald-500/10'
  if (v >= 0.85) return 'text-amber-200 border-amber-300/40 bg-amber-500/10'
  return 'text-rose-200 border-rose-300/40 bg-rose-500/10'
}

export default function Queue() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [busyId, setBusyId] = useState(null)

  async function refresh() {
    setErr('')
    try {
      const r = await listPending(200)
      setRows(r)
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function confirm(id) {
    setBusyId(id)
    try {
      await verifyRead(id, { action: 'confirm', user: 'reviewer' })
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  async function correct(id, corrected_text, corrected_province, note = '') {
    setBusyId(id)
    try {
      await verifyRead(id, { action: 'correct', corrected_text, corrected_province, note, user: 'reviewer' })
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  async function remove(id) {
    setBusyId(id)
    setErr('')
    try {
      await deleteRead(id)
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-blue-300/20 bg-gradient-to-r from-blue-600/20 to-cyan-500/10 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-slate-100">Verification Queue</h1>
            <div className="text-sm text-slate-300">ตรวจผล OCR และยืนยัน/แก้ไขก่อนบันทึกเข้า Master</div>
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-blue-200/30 bg-blue-500/10 px-3 py-1 text-xs text-blue-100">Pending {rows.length}</span>
            <button className="btn-blue" onClick={refresh}>Refresh</button>
          </div>
        </div>
      </div>

      {err && <div className="rounded-xl border border-rose-300/40 bg-rose-500/10 p-3 text-rose-200">{err}</div>}

      <div className="space-y-4">
        {rows.map((r) => (
          <QueueItem
            key={r.id}
            r={r}
            busy={busyId === r.id}
            onConfirm={() => confirm(r.id)}
            onCorrect={(t, p, n) => correct(r.id, t, p, n)}
            onDelete={() => remove(r.id)}
          />
        ))}
        {!rows.length && !err && <div className="rounded-2xl border border-blue-300/20 bg-slate-900/50 p-10 text-center text-slate-300">No pending items.</div>}
      </div>
    </div>
  )
}

function QueueItem({ r, busy, onConfirm, onCorrect, onDelete }) {
  const [t, setT] = useState(r.plate_text || '')
  const [p, setP] = useState(r.province || '')
  const [note, setNote] = useState('')
  const provinceMissing = !p.trim()

  function normalizePlateText(raw) {
    return (raw || '')
      .trim()
      .replace(/[\s\-.]/g, '')
      .replace(/[๐-๙]/g, (d) => '๐๑๒๓๔๕๖๗๘๙'.indexOf(d))
      .toUpperCase()
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.ctrlKey) {
      e.preventDefault()
      onConfirm()
    }
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault()
      onCorrect(t, p, note)
    }
  }

  return (
    <div className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-4 shadow-lg shadow-blue-950/10">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[520px_minmax(0,1fr)]">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">Original</div>
            <img className="h-40 w-full rounded-xl border border-blue-300/20 bg-slate-950/40 object-contain" src={absImageUrl(r.original_url)} />
          </div>
          <div>
            <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">Crop plate</div>
            <img className="h-40 w-full rounded-xl border border-blue-300/20 bg-slate-950/40 object-contain" src={absImageUrl(r.crop_url)} />
          </div>
        </div>

        <div className="space-y-3" onKeyDown={onKeyDown} tabIndex={0}>
          <div className="flex items-center justify-between">
            <div className="text-sm text-slate-400">OCR Confidence</div>
            <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${confidenceClass(r.confidence ?? 0)}`}>
              {(r.confidence ?? 0).toFixed(3)}
            </span>
          </div>

          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <label className="text-sm font-medium text-slate-200">
              Plate
              <input className="input-dark" value={t} onChange={(e) => setT(e.target.value)} />
            </label>
            <label className="text-sm font-medium text-slate-200">
              Province
              <input className="input-dark" placeholder="ยังอ่านจังหวัดไม่ได้" value={p} onChange={(e) => setP(e.target.value)} />
              {provinceMissing && <div className="mt-1 text-xs text-amber-200">ยังอ่านจังหวัดไม่ได้ - สามารถยืนยันหรือแก้ไขได้</div>}
            </label>
          </div>

          <label className="text-sm font-medium text-slate-200">
            Note
            <input className="input-dark" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button disabled={busy} onClick={onConfirm} className="btn-blue disabled:opacity-50">Confirm <span className="text-xs text-blue-100/90">Enter</span></button>
            <button disabled={busy} onClick={() => onCorrect(t, p, note)} className="btn-soft disabled:opacity-50">Save correction <span className="text-xs text-slate-300">Ctrl+Enter</span></button>
            <button type="button" className="btn-soft" onClick={() => setT(normalizePlateText(t))}>Normalize text</button>
            <button
              type="button"
              className="btn-soft border border-rose-300/40 text-rose-200 hover:border-rose-300/70"
              disabled={busy}
              onClick={() => {
                if (window.confirm('ลบรายการนี้ออกจากคิวตรวจสอบใช่หรือไม่?')) {
                  onDelete()
                }
              }}
            >
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
