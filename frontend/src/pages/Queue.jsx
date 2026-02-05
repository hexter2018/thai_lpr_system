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
      <div className="flex items-center justify-between mb-3">
        <h1 className="text-xl font-bold">Verification Queue</h1>
        <button className="px-3 py-2 rounded border" onClick={refresh}>Refresh</button>
      </div>

      {err && <div className="text-red-600 mb-3">{err}</div>}

      <div className="space-y-3">
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
    <div className="border rounded p-3">
      <div className="flex flex-col md:flex-row gap-3">
        <div className="flex gap-3">
          <div>
            <div className="text-xs text-gray-500 mb-1">Original</div>
            <img className="w-56 h-36 object-contain border rounded" src={absImageUrl(r.original_url)} />
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-1">Crop plate</div>
            <img className="w-56 h-36 object-contain border rounded" src={absImageUrl(r.crop_url)} />
          </div>
        </div>

        <div className="flex-1 space-y-2" onKeyDown={onKeyDown} tabIndex={0}>
          <div className="text-sm text-gray-600">
            Confidence: <b>{(r.confidence ?? 0).toFixed(3)}</b>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <label className="text-sm">
              Plate
              <input className="mt-1 w-full border rounded px-2 py-1"
                value={t} onChange={e=>setT(e.target.value)} />
            </label>
            <label className="text-sm">
              Province
              <input className="mt-1 w-full border rounded px-2 py-1"
                value={p} onChange={e=>setP(e.target.value)} />
            </label>
          </div>

          <label className="text-sm">
            Note
            <input className="mt-1 w-full border rounded px-2 py-1"
              value={note} onChange={e=>setNote(e.target.value)} />
          </label>

          <div className="flex gap-2 pt-1">
            <button disabled={busy} onClick={onConfirm}
              className="px-3 py-2 rounded bg-black text-white disabled:opacity-50">
              Confirm (Enter)
            </button>
            <button disabled={busy} onClick={() => onCorrect(t,p,note)}
              className="px-3 py-2 rounded border disabled:opacity-50">
              Save correction (Ctrl+Enter)
            </button>
          </div>

          <div className="text-xs text-gray-500">
            Tips: Click inside this card then press <b>Enter</b> to confirm, <b>Ctrl+Enter</b> to save correction.
          </div>
        </div>
      </div>
    </div>
  )
}
