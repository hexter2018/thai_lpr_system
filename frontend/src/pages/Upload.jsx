import React, { useState } from 'react'
import { uploadBatch, uploadSingle } from '../lib/api.js'
import { Button, Card, PageHeader } from '../components/ui.jsx'

export default function Upload() {
  const [single, setSingle] = useState(null)
  const [multi, setMulti] = useState([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)

  async function onUploadSingle() {
    if (!single) return
    setBusy(true)
    setMsg('Uploading single image...')
    try {
      const r = await uploadSingle(single)
      setMsg(`✅ Uploaded capture_id=${r.capture_id}`)
    } catch (e) {
      setMsg(`❌ ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  async function onUploadBatch() {
    if (!multi.length) return
    setBusy(true)
    setMsg('Uploading batch...')
    try {
      const r = await uploadBatch(multi)
      setMsg(`✅ Uploaded batch count=${r.count}`)
    } catch (e) {
      setMsg(`❌ ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  function onDrop(e) {
    e.preventDefault()
    setDragging(false)
    const files = Array.from(e.dataTransfer.files || [])
    if (!files.length) return
    setSingle(files[0])
    setMulti(files)
  }

  return (
    <div>
      <PageHeader title="Upload" subtitle="ลากไฟล์ภาพเพื่อส่งเข้า OCR pipeline ได้ทั้งเดี่ยวและแบบชุด" />
      {msg && <Card className="mb-4 text-blue-100">{msg}</Card>}

      <Card
        className={`mb-4 border-dashed p-8 text-center ${dragging ? 'border-blue-300/60 bg-blue-600/10' : 'border-blue-200/30'}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <p className="text-sm text-slate-300">Drag & drop images here</p>
        <p className="mt-2 text-xs text-slate-400">หรือเลือกไฟล์จากช่องด้านล่าง</p>
      </Card>

      <Card className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="text-sm text-slate-200">Single image
            <input className="mt-2 block w-full text-sm" type="file" accept="image/*" onChange={(e) => setSingle(e.target.files?.[0] || null)} />
          </label>
          <label className="text-sm text-slate-200">Batch images
            <input className="mt-2 block w-full text-sm" type="file" multiple accept="image/*" onChange={(e) => setMulti(Array.from(e.target.files || []))} />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy || !single} onClick={onUploadSingle}>Upload single</Button>
          <Button variant="secondary" disabled={busy || !multi.length} onClick={onUploadBatch}>Upload batch ({multi.length})</Button>
        </div>
      </Card>
    </div>
  )
}
