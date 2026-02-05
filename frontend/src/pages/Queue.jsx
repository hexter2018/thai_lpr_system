import React, { useEffect, useMemo, useState } from 'react'
import { absImageUrl, listPending, verifyRead } from '../lib/api.js'

export default function Queue() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState("")
  const [busyId, setBusyId] = useState(null)

  async function refresh() {
    setErr("")
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
      await verifyRead(id, { action: "confirm", user: "reviewer" })
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  async function correct(id, corrected_text, corrected_province, note="") {
    setBusyId(id)
    try {
      await verifyRead(id, { action: "correct", corrected_text, corrected_province, note, user: "reviewer" })
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Verification Queue</h1>
          <div className="text-sm text-slate-500">ตรวจผล OCR และยืนยัน/แก้ไขก่อนบันทึกเข้า Master</div>
        </div>

        <button
          className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-white shadow-sm hover:bg-blue-700 active:bg-blue-800"
          onClick={refresh}
        >
          <span className="text-sm font-medium">Refresh</span>
        </button>
      </div>

      {err && <div className="text-red-600 mb-3">{err}</div>}

      <div className="space-y-4">
        {rows.map(r => (
          <QueueItem key={r.id} r={r} busy={busyId===r.id}
            onConfirm={() => confirm(r.id)}
            onCorrect={(t,p,n) => correct(r.id,t,p,n)}
          />
        ))}
        {!rows.length && !err && <div className="text-gray-500">No pending items.</div>}
      </div>
    </div>
  )
}

function QueueItem({r, busy, onConfirm, onCorrect}) {
  const [t, setT] = useState(r.plate_text || "")
  const [p, setP] = useState(r.province || "")
  const [note, setNote] = useState("")

  // Hotkeys: Enter=Confirm, Ctrl+Enter=Save(correct) & Next (handled by page refresh)
  function onKeyDown(e) {
    if (e.key === "Enter" && !e.ctrlKey) {
      e.preventDefault()
      onConfirm()
    }
    if (e.key === "Enter" && e.ctrlKey) {
      e.preventDefault()
      onCorrect(t, p, note)
    }
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col lg:flex-row gap-4">
        <div className="flex gap-3">
          <div>
            <div className="text-xs text-slate-500 mb-1">Original</div>
            <img className="w-56 h-36 object-contain border border-slate-200 rounded-xl bg-slate-50" src={absImageUrl(r.original_url)} />
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Crop plate</div>
            <img className="w-56 h-36 object-contain border border-slate-200 rounded-xl bg-slate-50" src={absImageUrl(r.crop_url)} />
          </div>
        </div>

        <div className="flex-1 space-y-3" onKeyDown={onKeyDown} tabIndex={0}>
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm text-slate-600">
              Confidence
            </div>
            <div className={
              "inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold " +
              ((r.confidence ?? 0) >= 0.95 ? "bg-emerald-100 text-emerald-700" :
               (r.confidence ?? 0) >= 0.85 ? "bg-amber-100 text-amber-700" :
               "bg-rose-100 text-rose-700")
            }>
              {(r.confidence ?? 0).toFixed(3)}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <label className="text-sm">
              Plate
              <input className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:ring-2 focus:ring-blue-500"
                value={t} onChange={e=>setT(e.target.value)} />
            </label>
            <label className="text-sm">
              Province
              <input className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:ring-2 focus:ring-blue-500"
                value={p} onChange={e=>setP(e.target.value)} />
            </label>
          </div>

          <label className="text-sm">
            Note
            <input className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:ring-2 focus:ring-blue-500"
              value={note} onChange={e=>setNote(e.target.value)} />
          </label>

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              disabled={busy}
              onClick={onConfirm}
              className="inline-flex items-center justify-center rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 active:bg-blue-800 disabled:opacity-50"
            >
              Confirm <span className="ml-2 text-xs font-medium text-blue-100">Enter</span>
            </button>

            <button
              disabled={busy}
              onClick={() => onCorrect(t,p,note)}
              className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-50 active:bg-slate-100 disabled:opacity-50"
            >
              Save correction <span className="ml-2 text-xs font-medium text-slate-500">Ctrl+Enter</span>
            </button>
          </div>

          <div className="text-xs text-slate-500">
            Tips: Click inside this card then press <b>Enter</b> to confirm, <b>Ctrl+Enter</b> to save correction.
          </div>
        </div>
      </div>
    </div>
  )
}
