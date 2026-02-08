import React, { useEffect, useState } from 'react'
import { deleteMaster, searchMaster, upsertMaster, absImageUrl } from '../lib/api.js'

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

export default function Master() {
  const [q, setQ] = useState("")
  const [rows, setRows] = useState([])
  const [err, setErr] = useState("")
  const [msg, setMsg] = useState("")
  const [busy, setBusy] = useState(false)
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerImage, setViewerImage] = useState("")

  async function load() {
    setErr(""); setMsg("")
    try {
      const r = await searchMaster(q)
      // Fetch crop images for each master record
      const enriched = await Promise.all(
        r.map(async (row) => {
          try {
            const res = await fetch(`${API_BASE}/api/master/${row.id}/crops?limit=3`)
            if (res.ok) {
              const crops = await res.json()
              return { ...row, crops }
            }
          } catch (e) {
            console.warn('Failed to fetch crops for', row.id)
          }
          return { ...row, crops: [] }
        })
      )
      setRows(enriched)
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => { load() }, [])

  async function saveRow(row) {
    setBusy(true); setErr(""); setMsg("")
    try {
      await upsertMaster({
        plate_text_norm: row.plate_text_norm,
        display_text: row.display_text,
        province: row.province,
        confidence: row.confidence,
        editable: row.editable
      })
      setMsg("✓ บันทึกแล้ว")
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function removeRow(row) {
    if (!window.confirm(`ลบข้อมูลป้ายทะเบียน ${row.plate_text_norm} ใช่หรือไม่?`)) {
      return
    }
    setBusy(true); setErr(""); setMsg("")
    try {
      await deleteMaster(row.id)
      setMsg("✓ ลบแล้ว")
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  function openViewer(url) {
    setViewerImage(url)
    setViewerOpen(true)
  }

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-blue-300/20 bg-gradient-to-r from-blue-600/20 to-cyan-500/10 p-5">
        <h1 className="text-2xl font-semibold text-slate-100">Master Data</h1>
        <p className="text-sm text-slate-300">ฐานข้อมูลป้ายทะเบียนที่ยืนยันแล้ว พร้อมภาพ Crop ตัวอย่าง</p>
      </div>

      <div className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-4 shadow-lg">
        <div className="flex gap-2">
          <input
            className="input-dark flex-1"
            placeholder="ค้นหาป้ายทะเบียน..."
            value={q}
            onChange={e => setQ(e.target.value)}
          />
          <button className="btn-blue" onClick={load}>ค้นหา</button>
        </div>
      </div>

      {err && <div className="rounded-xl border border-rose-300/40 bg-rose-500/10 p-3 text-rose-200">{err}</div>}
      {msg && <div className="rounded-xl border border-emerald-300/40 bg-emerald-500/10 p-3 text-emerald-200">{msg}</div>}

      <div className="overflow-x-auto rounded-2xl border border-blue-300/20 bg-slate-900/55 shadow-lg">
        <table className="w-full text-sm">
          <thead className="border-b border-blue-200/20 bg-slate-950/40">
            <tr>
              <th className="p-3 text-left text-slate-300">Crop Images</th>
              <th className="p-3 text-left text-slate-300">Plate (Normalized)</th>
              <th className="p-3 text-left text-slate-300">Display Text</th>
              <th className="p-3 text-left text-slate-300">Province</th>
              <th className="p-3 text-left text-slate-300">Confidence</th>
              <th className="p-3 text-left text-slate-300">Seen Count</th>
              <th className="p-3 text-left text-slate-300">Editable</th>
              <th className="p-3 text-left text-slate-300">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => <Row key={r.id} r={r} busy={busy} onSave={saveRow} onDelete={removeRow} onViewImage={openViewer} />)}
            {!rows.length && (
              <tr>
                <td className="p-4 text-center text-slate-500" colSpan="8">
                  ไม่พบข้อมูล
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {viewerOpen && (
        <ImageViewer src={viewerImage} onClose={() => setViewerOpen(false)} />
      )}
    </div>
  )
}

function Row({ r, onSave, onDelete, busy, onViewImage }) {
  const [display, setDisplay] = useState(r.display_text || "")
  const [prov, setProv] = useState(r.province || "")
  const [conf, setConf] = useState(r.confidence ?? 1.0)
  const [editable, setEditable] = useState(!!r.editable)

  return (
    <tr className="border-b border-slate-800 hover:bg-slate-800/30">
      <td className="p-3">
        <div className="flex gap-1">
          {(r.crops || []).slice(0, 3).map((crop, i) => (
            <img
              key={i}
              src={absImageUrl(crop.crop_url)}
              alt="crop"
              className="h-12 w-16 cursor-pointer rounded border border-blue-200/20 object-cover hover:border-blue-300/50"
              onClick={() => onViewImage(absImageUrl(crop.crop_url))}
            />
          ))}
          {(!r.crops || r.crops.length === 0) && (
            <span className="text-xs text-slate-500">ไม่มีภาพ</span>
          )}
        </div>
      </td>
      <td className="p-3 font-mono text-slate-100">{r.plate_text_norm}</td>
      <td className="p-3">
        <input
          className="input-dark w-full"
          value={display}
          onChange={e => setDisplay(e.target.value)}
        />
      </td>
      <td className="p-3">
        <input
          className="input-dark w-full"
          value={prov}
          onChange={e => setProv(e.target.value)}
        />
      </td>
      <td className="p-3">
        <input
          className="input-dark w-28"
          type="number"
          step="0.001"
          value={conf}
          onChange={e => setConf(parseFloat(e.target.value))}
        />
      </td>
      <td className="p-3 text-slate-300">{r.count_seen}</td>
      <td className="p-3">
        <input
          type="checkbox"
          checked={editable}
          onChange={e => setEditable(e.target.checked)}
          className="h-4 w-4"
        />
      </td>
      <td className="p-3">
        <div className="flex flex-wrap gap-2">
          <button
            disabled={busy}
            className="btn-blue text-xs disabled:opacity-50"
            onClick={() => onSave({ ...r, display_text: display, province: prov, confidence: conf, editable })}
          >
            Save
          </button>
          <button
            disabled={busy}
            className="rounded-xl border border-rose-300/60 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-100 hover:bg-rose-500/20 disabled:opacity-50"
            onClick={() => onDelete(r)}
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  )
}

function ImageViewer({ src, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/90" onClick={onClose}>
      <div className="relative max-h-[90vh] max-w-[90vw]" onClick={e => e.stopPropagation()}>
        <img src={src} alt="full" className="max-h-[90vh] max-w-[90vw] rounded-xl border border-blue-300/30 shadow-2xl" />
        <button
          className="absolute right-2 top-2 rounded-lg border border-white/20 bg-slate-900/80 px-3 py-1.5 text-sm text-slate-100 hover:border-white/40"
          onClick={onClose}
        >
          ✕ ปิด
        </button>
      </div>
    </div>
  )
}
