import React, { useEffect, useMemo, useRef, useState } from 'react'
import { absImageUrl, listPending, verifyRead } from '../lib/api.js'
import { Badge, Button, Card, Input, PageHeader } from '../components/ui.jsx'

export default function Queue() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [busyId, setBusyId] = useState(null)

  async function refresh() {
    setErr('')
    try {
      setRows(await listPending(200))
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => { refresh() }, [])

  async function onAction(id, payload) {
    setBusyId(id)
    try {
      await verifyRead(id, payload)
      const idx = rows.findIndex((r) => r.id === id)
      await refresh()
      if (idx >= 0) {
        const next = document.querySelector(`[data-queue-card="${idx + 1}"] input[data-plate-input="1"]`)
        if (next) next.focus()
      }
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title="Verification Queue"
        subtitle="ตรวจผล OCR และยืนยัน/แก้ไขก่อนบันทึกเข้า Master"
        action={<Button onClick={refresh}>Refresh ({rows.length})</Button>}
      />
      {err && <Card className="mb-3 border-rose-300/30 text-rose-200">{err}</Card>}
      <div className="space-y-3">
        {rows.map((r, idx) => (
          <QueueItem key={r.id} r={r} idx={idx} busy={busyId === r.id} onAction={onAction} />
        ))}
        {!rows.length && !err && <Card className="text-center text-slate-400">No pending items.</Card>}
      </div>
    </div>
  )
}

function QueueItem({ r, idx, busy, onAction }) {
  const [t, setT] = useState(r.plate_text || '')
  const [p, setP] = useState(r.province || '')
  const [note, setNote] = useState('')
  const cardRef = useRef(null)

  const normalized = useMemo(() => (t || '').trim().replace(/[\s\-.]/g, '').replace(/[๐-๙]/g, (d) => '๐๑๒๓๔๕๖๗๘๙'.indexOf(d)).toUpperCase(), [t])

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.ctrlKey) {
      e.preventDefault()
      onAction(r.id, { action: 'confirm', user: 'reviewer' })
    }
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault()
      onAction(r.id, { action: 'correct', corrected_text: t, corrected_province: p, note, user: 'reviewer' })
    }
  }

  return (
    <Card className="p-4" data-queue-card={idx} ref={cardRef} onClick={() => cardRef.current?.querySelector('input[data-plate-input="1"]')?.focus()}>
      <div className="grid gap-4 xl:grid-cols-[480px_minmax(0,1fr)]" onKeyDown={onKeyDown}>
        <div className="grid gap-3 sm:grid-cols-2">
          <img className="h-40 w-full rounded-xl border border-blue-200/20 object-contain" src={absImageUrl(r.original_url)} />
          <img className="h-40 w-full rounded-xl border border-blue-200/20 object-contain" src={absImageUrl(r.crop_url)} />
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm text-slate-300">
            <span>OCR confidence</span>
            <Badge score={r.confidence ?? 0} />
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="text-sm">Plate<Input data-plate-input="1" value={t} onChange={(e) => setT(e.target.value)} /></label>
            <label className="text-sm">Province<Input value={p} onChange={(e) => setP(e.target.value)} /></label>
          </div>
          <label className="text-sm">Note<Input value={note} onChange={(e) => setNote(e.target.value)} /></label>
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy} onClick={() => onAction(r.id, { action: 'confirm', user: 'reviewer' })}>Confirm (Enter)</Button>
            <Button variant="secondary" disabled={busy} onClick={() => onAction(r.id, { action: 'correct', corrected_text: t, corrected_province: p, note, user: 'reviewer' })}>Save correction (Ctrl+Enter)</Button>
            <Button variant="secondary" onClick={() => setT(normalized)}>Normalize text</Button>
          </div>
        </div>
      </div>
    </Card>
  )
}
