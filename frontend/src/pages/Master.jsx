import React, { useEffect, useState } from 'react'
import { searchMaster, upsertMaster } from '../lib/api.js'

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

  return (
    <div>
      <h1 className="text-xl font-bold mb-3">Master Data</h1>
      <div className="flex gap-2 mb-3">
        <input className="border rounded px-2 py-1 w-full"
          placeholder="Search plate_text_norm..."
          value={q} onChange={e=>setQ(e.target.value)} />
        <button className="px-3 py-2 rounded border" onClick={load}>Search</button>
      </div>

      {err && <div className="text-red-600 mb-3">{err}</div>}
      {msg && <div className="text-green-700 mb-3">{msg}</div>}

      <div className="overflow-auto border rounded">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
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
            {rows.map(r => <Row key={r.id} r={r} busy={busy} onSave={saveRow} />)}
            {!rows.length && <tr><td className="p-2 text-gray-500" colSpan="7">No records</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Row({r, onSave, busy}) {
  const [display, setDisplay] = useState(r.display_text || "")
  const [prov, setProv] = useState(r.province || "")
  const [conf, setConf] = useState(r.confidence ?? 1.0)
  const [editable, setEditable] = useState(!!r.editable)

  return (
    <tr className="border-t">
      <td className="p-2 font-mono">{r.plate_text_norm}</td>
      <td className="p-2">
        <input className="border rounded px-2 py-1 w-full"
          value={display} onChange={e=>setDisplay(e.target.value)} />
      </td>
      <td className="p-2">
        <input className="border rounded px-2 py-1 w-full"
          value={prov} onChange={e=>setProv(e.target.value)} />
      </td>
      <td className="p-2">
        <input className="border rounded px-2 py-1 w-24"
          type="number" step="0.001"
          value={conf} onChange={e=>setConf(parseFloat(e.target.value))} />
      </td>
      <td className="p-2">{r.count_seen}</td>
      <td className="p-2">
        <input type="checkbox" checked={editable} onChange={e=>setEditable(e.target.checked)} />
      </td>
      <td className="p-2">
        <button disabled={busy} className="px-3 py-1 rounded border"
          onClick={() => onSave({
            ...r,
            display_text: display,
            province: prov,
            confidence: conf,
            editable
          })}>
          Save
        </button>
      </td>
    </tr>
  )
}
