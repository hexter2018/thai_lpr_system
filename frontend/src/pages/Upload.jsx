import React, { useState } from 'react'
import { uploadSingle, uploadBatch } from '../lib/api.js'

export default function Upload() {
  const [single, setSingle] = useState(null)
  const [multi, setMulti] = useState([])
  const [msg, setMsg] = useState("")
  const [busy, setBusy] = useState(false)

  async function onUploadSingle() {
    if (!single) return
    setBusy(true); setMsg("")
    try {
      const r = await uploadSingle(single)
      setMsg(`Uploaded capture_id=${r.capture_id}`)
    } catch (e) {
      setMsg(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onUploadBatch() {
    if (!multi.length) return
    setBusy(true); setMsg("")
    try {
      const r = await uploadBatch(multi)
      setMsg(`Uploaded batch: count=${r.count}`)
    } catch (e) {
      setMsg(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Upload</h1>

      {msg && <div className="p-3 border rounded bg-gray-50 text-sm">{msg}</div>}

      <section className="border rounded p-4">
        <div className="font-semibold mb-2">Single Image</div>
        <input type="file" accept="image/*" onChange={(e) => setSingle(e.target.files?.[0] || null)} />
        <div className="mt-3">
          <button disabled={busy || !single} onClick={onUploadSingle}
            className="px-3 py-2 rounded bg-black text-white disabled:opacity-50">
            Upload single
          </button>
        </div>
      </section>

      <section className="border rounded p-4">
        <div className="font-semibold mb-2">Multiple Images</div>
        <input type="file" accept="image/*" multiple onChange={(e) => setMulti(Array.from(e.target.files || []))} />
        <div className="mt-3">
          <button disabled={busy || !multi.length} onClick={onUploadBatch}
            className="px-3 py-2 rounded bg-black text-white disabled:opacity-50">
            Upload batch ({multi.length})
          </button>
        </div>
      </section>

      <div className="text-sm text-gray-600">
        After upload, the worker processes asynchronously. Go to <b>Verification Queue</b> to review results.
      </div>
    </div>
  )
}
