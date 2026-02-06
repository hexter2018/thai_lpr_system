import React, { useEffect, useState } from 'react'
import { searchMaster, upsertMaster } from '../lib/api.js'
import { Button, Card, Input, PageHeader } from '../components/ui.jsx'

export default function Master() {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    setErr(''); setMsg('')
    try {
      setRows(await searchMaster(q))
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => { load() }, [])

  async function saveRow(row) {
    setBusy(true); setErr(''); setMsg('')
    try {
      await upsertMaster(row)
      setMsg('Saved')
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader title="Master Data" subtitle="ค้นหาและแก้ไขข้อมูลทะเบียนที่ยืนยันแล้ว" />
      <Card className="mb-3">
        <div className="flex gap-2">
          <Input placeholder="Search plate_text_norm..." value={q} onChange={(e) => setQ(e.target.value)} className="mt-0" />
          <Button onClick={load}>Search</Button>
        </div>
      </Card>
      {err && <Card className="mb-3 border-rose-300/30 text-rose-200">{err}</Card>}
      {msg && <Card className="mb-3 text-emerald-200">{msg}</Card>}

      <div className="overflow-auto rounded-2xl border border-blue-200/20">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-slate-900">
            <tr>
              {['plate_text_norm', 'display_text', 'province', 'confidence', 'count', 'editable', ''].map((h) => (
                <th key={h} className="px-3 py-2 text-left text-slate-300">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => <Row key={r.id} r={r} busy={busy} onSave={saveRow} striped={i % 2 === 1} />)}
            {!rows.length && <tr><td className="p-3 text-slate-400" colSpan="7">No records</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Row({ r, onSave, busy, striped }) {
  const [display, setDisplay] = useState(r.display_text || '')
  const [prov, setProv] = useState(r.province || '')
  const [conf, setConf] = useState(r.confidence ?? 1.0)
  const [editable, setEditable] = useState(!!r.editable)

  return (
    <tr className={`${striped ? 'bg-slate-900/50' : 'bg-slate-950/40'} border-t border-blue-200/10`}>
      <td className="p-2 font-mono">{r.plate_text_norm}</td>
      <td className="p-2"><Input className="mt-0" value={display} onChange={(e) => setDisplay(e.target.value)} /></td>
      <td className="p-2"><Input className="mt-0" value={prov} onChange={(e) => setProv(e.target.value)} /></td>
      <td className="p-2"><Input className="mt-0 w-24" type="number" step="0.001" value={conf} onChange={(e) => setConf(parseFloat(e.target.value))} /></td>
      <td className="p-2">{r.count_seen}</td>
      <td className="p-2"><input type="checkbox" checked={editable} onChange={(e) => setEditable(e.target.checked)} /></td>
      <td className="p-2"><Button disabled={busy} onClick={() => onSave({ ...r, display_text: display, province: prov, confidence: conf, editable })}>Save</Button></td>
    </tr>
  )
}
