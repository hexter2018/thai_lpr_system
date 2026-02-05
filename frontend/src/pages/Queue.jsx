import React, { useEffect, useState } from 'react'
import { absImageUrl, listPending, verifyRead } from '../lib/api.js'

function confidenceClass(v) {
  if (v >= 0.95) return 'bg-emerald-100 text-emerald-700 border border-emerald-200'
  if (v >= 0.85) return 'bg-amber-100 text-amber-700 border border-amber-200'
  return 'bg-rose-100 text-rose-700 border border-rose-200'
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

  useEffect(() => { refresh() }, [])

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

  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">Verification Queue</h1>
            <div className="text-sm text-slate-500">ตรวจผล OCR และยืนยัน/แก้ไขก่อนบันทึกเข้า Master</div>
          </div>
          <div className="flex items-center gap-2">
            <span className="badge-slate">Pending {rows.length}</span>
            <button className="btn-primary" onClick={refresh}>Refresh</button>
          </div>
        </div>
      </div>

      {err && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-rose-700">{err}</div>}

      <div className="space-y-4">
        {rows.map((r) => (
          <QueueItem
            key={r.id}
            r={r}
            busy={busyId === r.id}
            onConfirm={() => confirm(r.id)}
            onCorrect={(t, p, n) => correct(r.id, t, p, n)}
          />
        ))}
        {!rows.length && !err && (
          <div className="card p-10 text-center text-slate-500">No pending items.</div>
        )}
      </div>
    </div>
  )
}

function QueueItem({ r, busy, onConfirm, onCorrect }) {
  const [t, setT] = useState(r.plate_text || '')
  const [p, setP] = useState(r.province || '')
  const [note, setNote] = useState('')

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
    <div className="card p-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[530px_minmax(0,1fr)]">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Original</div>
            <img className="h-40 w-full rounded-xl border border-slate-200 bg-slate-50 object-contain" src={absImageUrl(r.original_url)} />
          </div>
          <div>
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Crop plate</div>
            <img className="h-40 w-full rounded-xl border border-slate-200 bg-slate-50 object-contain" src={absImageUrl(r.crop_url)} />
          </div>
        </div>

        <div className="space-y-3" onKeyDown={onKeyDown} tabIndex={0}>
          <div className="flex items-center justify-between">
            <div className="text-sm text-slate-500">OCR Confidence</div>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${confidenceClass(r.confidence ?? 0)}`}>
              {(r.confidence ?? 0).toFixed(3)}
            </span>
          </div>

          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <label className="text-sm font-medium text-slate-700">
              Plate
              <input className="input" value={t} onChange={(e) => setT(e.target.value)} />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Province
              <input className="input" value={p} onChange={(e) => setP(e.target.value)} />
            </label>
          </div>

          <label className="text-sm font-medium text-slate-700">
            Note
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button disabled={busy} onClick={onConfirm} className="btn-primary disabled:opacity-50">
              Confirm <span className="text-xs text-blue-100">Enter</span>
            </button>
            <button disabled={busy} onClick={() => onCorrect(t, p, note)} className="btn-ghost disabled:opacity-50">
              Save correction <span className="text-xs text-slate-500">Ctrl+Enter</span>
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setT(normalizePlateText(t))}
            >
              Normalize text
            </button>
          </div>

          <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
            Tips: กด <b>Normalize text</b> เพื่อล้างช่องว่าง/ขีด และแปลงเลขไทยเป็นเลขอารบิก ช่วยลด OCR ผิดก่อนบันทึก.
          </div>
        </div>
      </div>
    </div>
  )
}
