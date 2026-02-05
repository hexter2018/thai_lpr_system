import React, { useEffect, useState } from 'react'
import { absImageUrl, listPending, verifyRead } from '../lib/api.js'

export default function Queue() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setErr('')
    setLoading(true)
    try {
      const r = await listPending(200)
      setRows(r)
    } catch (e) {
      setErr(String(e))
    } finally {
      setLoading(false)
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
    <div className="min-h-full rounded-2xl border border-blue-100 bg-gradient-to-b from-blue-50 via-white to-blue-100/70 p-4 shadow-sm md:p-6">
      <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-blue-950">Verification Queue</h1>
          <p className="mt-1 text-sm text-blue-700">ปรับแก้ผลอ่านทะเบียนให้ถูกต้องก่อนยืนยันเข้าระบบ</p>
        </div>

        <div className="flex items-center gap-2">
          <span className="rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-semibold text-blue-700">
            Pending {rows.length}
          </span>
          <button
            className="rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm font-medium text-blue-700 shadow-sm transition hover:border-blue-400 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
            onClick={refresh}
            disabled={loading}
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {err && <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-red-700">{err}</div>}

      <div className="space-y-3">
        {rows.map((r) => (
          <QueueItem
            key={r.id}
            r={r}
            busy={busyId === r.id}
            onConfirm={() => confirm(r.id)}
            onCorrect={(t, p, n) => correct(r.id, t, p, n)}
          />
        ))}

        {!rows.length && !err && !loading && (
          <div className="rounded-xl border border-dashed border-blue-300 bg-white/90 p-8 text-center text-blue-700">
            No pending items.
          </div>
        )}
      </div>
    </div>
  )
}

function QueueItem({ r, busy, onConfirm, onCorrect }) {
  const [t, setT] = useState(r.plate_text || '')
  const [p, setP] = useState(r.province || '')
  const [note, setNote] = useState('')

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

  const confidence = Number(r.confidence ?? 0)
  const confidenceTone = confidence >= 0.8 ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : confidence >= 0.5 ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-rose-50 text-rose-700 border-rose-200'

  return (
    <div className="overflow-hidden rounded-xl border border-blue-200 bg-white p-3 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md md:p-4">
      <div className="flex flex-col gap-4 md:flex-row">
        <div className="flex flex-wrap gap-3">
          <ImagePreview label="Original" src={absImageUrl(r.original_url)} />
          <ImagePreview label="Crop plate" src={absImageUrl(r.crop_url)} />
        </div>

        <div className="flex-1 space-y-3 rounded-lg border border-blue-100 bg-blue-50/40 p-3" onKeyDown={onKeyDown} tabIndex={0}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-medium text-blue-900">Review #{r.id}</div>
            <div className={`rounded-full border px-3 py-1 text-xs font-semibold ${confidenceTone}`}>
              Confidence {(r.confidence ?? 0).toFixed(3)}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <label className="text-sm font-medium text-blue-900">
              Plate
              <input
                className="mt-1 w-full rounded-md border border-blue-200 bg-white px-2 py-2 outline-none ring-blue-300 transition focus:ring"
                value={t}
                onChange={(e) => setT(e.target.value)}
                placeholder="เช่น ฆต 3300"
              />
            </label>
            <label className="text-sm font-medium text-blue-900">
              Province
              <input
                className="mt-1 w-full rounded-md border border-blue-200 bg-white px-2 py-2 outline-none ring-blue-300 transition focus:ring"
                value={p}
                onChange={(e) => setP(e.target.value)}
                placeholder="เช่น กรุงเทพมหานคร"
              />
            </label>
          </div>

          <label className="text-sm font-medium text-blue-900">
            Note
            <input
              className="mt-1 w-full rounded-md border border-blue-200 bg-white px-2 py-2 outline-none ring-blue-300 transition focus:ring"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="หมายเหตุเพิ่มเติม (ถ้ามี)"
            />
          </label>

          <div className="flex flex-col gap-2 pt-1 sm:flex-row">
            <button
              disabled={busy}
              onClick={onConfirm}
              className="rounded-md bg-blue-700 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Confirm (Enter)
            </button>
            <button
              disabled={busy}
              onClick={() => onCorrect(t, p, note)}
              className="rounded-md border border-blue-300 bg-white px-4 py-2 text-sm font-semibold text-blue-700 transition hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Save correction (Ctrl+Enter)
            </button>
          </div>

          <div className="text-xs text-blue-600">
            Tips: Click inside this card then press <b>Enter</b> to confirm, <b>Ctrl+Enter</b> to save correction.
          </div>
        </div>
      </div>
    </div>
  )
}

function ImagePreview({ label, src }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-blue-500">{label}</div>
      <img className="h-36 w-56 rounded-lg border border-blue-100 bg-slate-900/90 object-contain" src={src} />
    </div>
  )
}
