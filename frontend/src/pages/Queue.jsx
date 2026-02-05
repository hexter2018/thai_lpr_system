import React, { useEffect, useState } from 'react'
import { absImageUrl, listPending, verifyRead } from '../lib/api.js'

function confidenceClass(v) {
  if (v >= 0.95) return 'bg-emerald-400/15 text-emerald-200 border border-emerald-300/30'
  if (v >= 0.85) return 'bg-amber-400/15 text-amber-200 border border-amber-300/30'
  return 'bg-rose-400/15 text-rose-200 border border-rose-300/30'
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

  return (
    <div className="space-y-4">
      <section className="glass rounded-2xl p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-2xl font-semibold text-white">Verification Queue</h2>
            <p className="text-sm text-slate-300">ตรวจผล OCR และยืนยัน/แก้ไขก่อนบันทึกเข้า Master</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="badge-blue">Pending {rows.length}</span>
            <button className="btn-primary" onClick={refresh}>Refresh</button>
          </div>
        </div>
      </section>

      {err && <div className="rounded-xl border border-rose-300/40 bg-rose-500/10 p-3 text-rose-100">{err}</div>}

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
        {!rows.length && !err && <div className="glass rounded-2xl p-8 text-center text-slate-300">No pending items.</div>}
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
    <article className="glass rounded-2xl p-4" onKeyDown={onKeyDown} tabIndex={0}>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[520px_minmax(0,1fr)]">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-xs uppercase tracking-[0.14em] text-slate-300">Original</p>
            <img className="h-40 w-full rounded-xl border border-white/15 bg-slate-900/40 object-contain" src={absImageUrl(r.original_url)} />
          </div>
          <div>
            <p className="mb-1 text-xs uppercase tracking-[0.14em] text-slate-300">Crop plate</p>
            <img className="h-40 w-full rounded-xl border border-white/15 bg-slate-900/40 object-contain" src={absImageUrl(r.crop_url)} />
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-300">OCR Confidence</p>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${confidenceClass(r.confidence ?? 0)}`}>
              {(r.confidence ?? 0).toFixed(3)}
            </span>
          </div>

          <div className="grid gap-2 md:grid-cols-2">
            <label className="text-sm font-medium text-slate-200">
              Plate
              <input className="input" value={t} onChange={(e) => setT(e.target.value)} />
            </label>
            <label className="text-sm font-medium text-slate-200">
              Province
              <input className="input" value={p} onChange={(e) => setP(e.target.value)} />
            </label>
          </div>

          <label className="text-sm font-medium text-slate-200">
            Note
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>

          <div className="flex flex-wrap gap-2 pt-1">
            <button disabled={busy} onClick={onConfirm} className="btn-primary disabled:opacity-50">
              Confirm <span className="text-xs text-blue-100">Enter</span>
            </button>
            <button disabled={busy} onClick={() => onCorrect(t, p, note)} className="btn-secondary disabled:opacity-50">
              Save correction <span className="text-xs text-slate-200">Ctrl+Enter</span>
            </button>
            <button type="button" className="btn-secondary" onClick={() => setT(normalizePlateText(t))}>
              Normalize text
            </button>
          </div>
        </div>
      </div>
    </article>
  )
}
