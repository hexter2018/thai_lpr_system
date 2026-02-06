import React, { useEffect, useState } from 'react'
import { listCameras, upsertCamera, rtspStart, rtspStop } from '../lib/api.js'
import { Button, Card, Input, PageHeader } from '../components/ui.jsx'

export default function Rtsp() {
  const [cams, setCams] = useState([])
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const [camera_id, setCameraId] = useState('plaza2-lane1')
  const [name, setName] = useState('plaza2 lane 1')
  const [rtsp_url, setUrl] = useState('rtsp://user:pass@ip/stream')
  const [fps, setFps] = useState(2.0)

  async function refresh() {
    setErr(''); setMsg('')
    try {
      setCams(await listCameras())
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => { refresh() }, [])

  async function onSaveCamera() {
    setErr(''); setMsg('')
    try {
      await upsertCamera({ camera_id, name, rtsp_url, enabled: true })
      setMsg('Camera saved')
      await refresh()
    } catch (e) {
      setErr(String(e))
    }
  }

  async function onStart() {
    setErr(''); setMsg('')
    try {
      await rtspStart({ camera_id, rtsp_url, fps: parseFloat(fps), reconnect_sec: 2.0 })
      setMsg('RTSP ingest started (worker)')
    } catch (e) {
      setErr(String(e))
    }
  }

  return (
    <div>
      <PageHeader title="RTSP" subtitle="จัดการกล้องและสั่งงาน ingest worker" action={<Button variant="secondary" onClick={refresh}>Refresh</Button>} />
      {err && <Card className="mb-3 border-rose-300/30 text-rose-200">{err}</Card>}
      {msg && <Card className="mb-3 text-emerald-200">{msg}</Card>}

      <Card className="mb-3 space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">camera_id<Input value={camera_id} onChange={(e) => setCameraId(e.target.value)} /></label>
          <label className="text-sm">name<Input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="text-sm md:col-span-2">rtsp_url<Input value={rtsp_url} onChange={(e) => setUrl(e.target.value)} /></label>
          <label className="text-sm">fps<Input type="number" step="0.1" value={fps} onChange={(e) => setFps(e.target.value)} /></label>
        </div>
        <div className="flex gap-2">
          <Button onClick={onSaveCamera}>Save camera</Button>
          <Button variant="secondary" onClick={onStart}>Start ingest</Button>
        </div>
      </Card>

      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-300">
              <th className="p-2">camera_id</th><th className="p-2">name</th><th className="p-2">enabled</th><th className="p-2">action</th>
            </tr>
          </thead>
          <tbody>
            {cams.map((c) => (
              <tr key={c.id} className="border-t border-blue-200/15">
                <td className="p-2 font-mono">{c.camera_id}</td>
                <td className="p-2">{c.name}</td>
                <td className="p-2">{String(c.enabled)}</td>
                <td className="p-2"><Button variant="danger" onClick={() => rtspStop(c.camera_id)}>Stop</Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
