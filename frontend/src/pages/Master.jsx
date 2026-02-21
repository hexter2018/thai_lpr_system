import React, { useEffect, useState } from 'react'
import { deleteMaster, searchMaster, upsertMaster, absImageUrl } from '../lib/api.js'

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "").replace(/\/api$/, "");

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
            const res = await fetch(`${API_BASE}/api/master/${row.id}/crops?limit=5`)
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
    <div className="w-full space-y-4">
      <div className="rounded-2xl border border-emerald-300/20 bg-gradient-to-r from-emerald-600/20 to-teal-500/10 p-5">
        <h1 className="text-2xl font-semibold text-slate-100">Master Data</h1>
        <p className="text-sm text-slate-300">ฐานข้อมูลป้ายทะเบียนที่ยืนยันแล้ว พร้อมภาพตัวอย่าง</p>
      </div>

      <div className="rounded-2xl border border-slate-700/50 bg-slate-900/55 p-4 shadow-lg">
        <div className="flex gap-2">
          <input
            className="input-dark flex-1"
            placeholder="ค้นหาป้ายทะเบียน..."
            value={q}
            onChange={e => setQ(e.target.value)}
          />
          <button className="btn-emerald" onClick={load}>ค้นหา</button>
        </div>
      </div>

      {err && <div className="rounded-xl border border-rose-300/40 bg-rose-500/10 p-3 text-rose-200">{err}</div>}
      {msg && <div className="rounded-xl border border-emerald-300/40 bg-emerald-500/10 p-3 text-emerald-200">{msg}</div>}

      <div className="overflow-x-auto rounded-2xl border border-slate-700/50 bg-slate-900/55 shadow-lg">
        <table className="w-full min-w-[1080px]text-sm">
          <thead className="border-b border-slate-700/50 bg-slate-950/40">
            <tr>
              <th className="p-3 text-left text-slate-300">ภาพตัวอย่าง</th>
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
    <tr className="border-b border-slate-800 hover:bg-slate-800/30 transition">
      <td className="p-3">
        {r.crops && r.crops.length > 0 ? (
          <div className="relative inline-block group">
            <img
              src={absImageUrl(r.crops[0].crop_url || r.crops[0].original_url)}
              alt="crop"
              className="h-16 w-24 cursor-zoom-in rounded-lg border border-slate-700/50 object-cover hover:border-emerald-400/50 transition shadow-sm"
              onClick={() => onViewImage(absImageUrl(r.crops[0].crop_url || r.crops[0].original_url))}
            />
            {r.crops.length > 1 && (
              <span className="absolute -bottom-1 -right-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-emerald-500 px-1 text-[10px] font-bold text-white shadow-lg ring-2 ring-slate-900">
                +{r.crops.length - 1}
              </span>
            )}
            <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/60 opacity-0 group-hover:opacity-100 transition">
              <span className="text-xs text-white">คลิกเพื่อขยาย</span>
            </div>
          </div>
        ) : (
          <div className="flex h-16 w-24 items-center justify-center rounded-lg border border-dashed border-slate-700 bg-slate-950/50">
            <span className="text-xs text-slate-600">ไม่มีภาพ</span>
          </div>
        )}
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
      <td className="p-3">
        <div className="flex items-center gap-2">
          <span className="text-slate-300">{r.count_seen}</span>
          <span className="text-xs text-slate-500">ครั้ง</span>
        </div>
      </td>
      <td className="p-3">
        <input
          type="checkbox"
          checked={editable}
          onChange={e => setEditable(e.target.checked)}
          className="h-4 w-4 accent-emerald-500"
        />
      </td>
      <td className="p-3">
        <div className="flex flex-wrap gap-2">
          <button
            disabled={busy}
            className="btn-emerald text-xs disabled:opacity-50"
            onClick={() => onSave({ ...r, display_text: display, province: prov, confidence: conf, editable })}
          >
            บันทึก
          </button>
          <button
            disabled={busy}
            className="rounded-xl border border-rose-300/60 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-100 hover:bg-rose-500/20 disabled:opacity-50 transition"
            onClick={() => onDelete(r)}
          >
            ลบ
          </button>
        </div>
      </td>
    </tr>
  )
}

function ImageViewer({ src, onClose }) {
  const [scale, setScale] = useState(1)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setScale(1)
    setLoading(true)
    setFailed(false)
  }, [src])

  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key === '+' || e.key === '=') setScale(s => Math.min(4, s + 0.2))
      if (e.key === '-') setScale(s => Math.max(0.5, s - 0.2))
      if (e.key === '0') setScale(1)
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  const handleWheel = (e) => {
    e.preventDefault()
    const delta = e.deltaY * -0.001
    setScale(s => Math.min(4, Math.max(0.5, s + delta)))
  }
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/90 backdrop-blur-sm" onClick={onClose}>
      <div className="relative h-[90vh] w-[94vw] max-w-6xl overflow-hidden rounded-xl border border-emerald-300/30 bg-slate-950/95" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-700/50 bg-slate-900/70 px-3 py-2">
          <div className="text-xs text-slate-300">ซูม {(scale * 100).toFixed(0)}% • เลื่อนล้อเมาส์เพื่อซูม</div>
          <div className="flex items-center gap-1.5">
            <button className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:border-slate-400" onClick={() => setScale(s => Math.max(0.5, s - 0.2))}>-</button>
            <button className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:border-slate-400" onClick={() => setScale(1)}>รีเซ็ต</button>
            <button className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:border-slate-400" onClick={() => setScale(s => Math.min(4, s + 0.2))}>+</button>
          </div>
        </div>
        <div className="relative h-[calc(100%-44px)] overflow-auto" onWheel={handleWheel}>
        {loading && !failed && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-slate-900/70 text-sm text-slate-200">
            กำลังโหลดรูป...
          </div>
        )}
        {failed && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-rose-950/50 text-sm text-rose-200">
            ไม่สามารถโหลดรูปภาพได้
          </div>
        )}
        <img
          src={src}
          alt="full"
          className="mx-auto mt-4 max-h-[80vh] max-w-[90vw] rounded-xl shadow-2xl"
          style={{ transform: `scale(${scale})`, transformOrigin: 'center center', transition: 'transform 0.08s ease-out' }}
          onLoad={() => setLoading(false)}
          onError={() => { setLoading(false); setFailed(true) }}
        />
        </div>
        <button
          className="absolute right-2 top-2 rounded-lg border border-white/20 bg-slate-900/80 px-3 py-1.5 text-sm text-slate-100 hover:border-white/40 transition backdrop-blur"
          onClick={onClose}
        >
          ✕ ปิด
        </button>
      </div>
    </div>
  )
}
