import React, { useEffect, useState } from 'react'
import { deleteMaster, searchMaster, upsertMaster } from '../lib/api.js'

export default function Master() {
  const [q, setQ] = useState("")
  const [rows, setRows] = useState([])
  const [err, setErr] = useState("")
  const [msg, setMsg] = useState("")
  const [busy, setBusy] = useState(false)

  async function load() {
    setErr(""); setMsg("")
    try {
      const r = await searchMaster(q)
      setRows(r)
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
      setMsg("Saved")
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
      setMsg("Deleted")
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h1 className="text-xl font-bold mb-3">Master Data</h1>
      <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm mb-3">
        <div className="flex gap-2">
          <input className="flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:ring-2 focus:ring-blue-200"
          placeholder="Search plate_text_norm..."
          value={q} onChange={e=>setQ(e.target.value)} />
          <button className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-medium shadow-sm hover:bg-blue-700 active:bg-blue-800" onClick={load}>Search</button>
        </div>
      </div>

      {err && <div className="text-red-600 mb-3">{err}</div>}
      {msg && <div className="text-green-700 mb-3">{msg}</div>}

      <div className="overflow-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="text-left p-2">plate_text_norm</th>
              <th className="text-left p-2">display_text</th>
              <th className="text-left p-2">province</th>
              <th className="text-left p-2">confidence</th>
              <th className="text-left p-2">count</th>
              <th className="text-left p-2">editable</th>
              <th className="text-left p-2"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => <Row key={r.id} r={r} busy={busy} onSave={saveRow} onDelete={removeRow} />)}
            {!rows.length && <tr><td className="p-3 text-slate-500" colSpan="7">No records</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Row({r, onSave, onDelete, busy}) {
  const [display, setDisplay] = useState(r.display_text || "")
  const [prov, setProv] = useState(r.province || "")
  const [conf, setConf] = useState(r.confidence ?? 1.0)
  const [editable, setEditable] = useState(!!r.editable)

  return (
    <tr className="border-t border-slate-100">
      <td className="p-2 font-mono">{r.plate_text_norm}</td>
      <td className="p-2">
        <input className="rounded-xl border border-slate-200 px-3 py-2 w-full text-sm focus:ring-2 focus:ring-blue-200"
          value={display} onChange={e=>setDisplay(e.target.value)} />
      </td>
      <td className="p-2">
        <input className="rounded-xl border border-slate-200 px-3 py-2 w-full text-sm focus:ring-2 focus:ring-blue-200"
          value={prov} onChange={e=>setProv(e.target.value)} />
      </td>
      <td className="p-2">
        <input className="rounded-xl border border-slate-200 px-3 py-2 w-28 text-sm focus:ring-2 focus:ring-blue-200"
          type="number" step="0.001"
          value={conf} onChange={e=>setConf(parseFloat(e.target.value))} />
      </td>
      <td className="p-2">{r.count_seen}</td>
      <td className="p-2">
        <input type="checkbox" checked={editable} onChange={e=>setEditable(e.target.checked)} />
      </td>
      <td className="p-2">
        <div className="flex flex-wrap gap-2">
          <button disabled={busy} className="px-3 py-2 rounded-xl bg-blue-600 text-white text-sm font-medium shadow-sm hover:bg-blue-700 disabled:opacity-60"
            onClick={() => onSave({
              ...r,
              display_text: display,
              province: prov,
              confidence: conf,
              editable
            })}>
            Save
          </button>
          <button
            disabled={busy}
            className="px-3 py-2 rounded-xl border border-rose-200 text-rose-600 text-sm font-medium shadow-sm hover:bg-rose-50 disabled:opacity-60"
            onClick={() => onDelete({
              ...r,
              display_text: display,
              province: prov,
              confidence: conf,
              editable
            })}
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  )
}
