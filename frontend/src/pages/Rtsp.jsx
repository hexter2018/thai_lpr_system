import React, { useEffect, useState } from 'react'
import { listCameras, upsertCamera, rtspStart, rtspStop } from '../lib/api.js'

export default function Rtsp() {
  const [cams, setCams] = useState([])
  const [err, setErr] = useState("")
  const [msg, setMsg] = useState("")

  const [camera_id, setCameraId] = useState("plaza2-lane1")
  const [name, setName] = useState("plaza2 lane 1")
  const [rtsp_url, setUrl] = useState("rtsp://user:pass@ip/stream")
  const [fps, setFps] = useState(2.0)

  async function refresh() {
    setErr(""); setMsg("")
    try {
      setCams(await listCameras())
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => { refresh() }, [])

  async function onSaveCamera() {
    setErr(""); setMsg("")
    try {
      await upsertCamera({ camera_id, name, rtsp_url, enabled: true })
      setMsg("Camera saved")
      await refresh()
    } catch (e) {
      setErr(String(e))
    }
  }

  async function onStart() {
    setErr(""); setMsg("")
    try {
      await rtspStart({ camera_id, rtsp_url, fps: parseFloat(fps), reconnect_sec: 2.0 })
      setMsg("RTSP ingest started (worker)")
    } catch (e) {
      setErr(String(e))
    }
  }

  async function onStop(id) {
    setErr(""); setMsg("")
    try {
      await rtspStop(id)
      setMsg(`RTSP stop requested for ${id}`)
    } catch (e) {
      setErr(String(e))
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">RTSP</h1>

      {err && <div className="text-red-600">{err}</div>}
      {msg && <div className="text-green-700">{msg}</div>}

      <div className="border rounded p-4 space-y-3">
        <div className="font-semibold">Add / Update Camera</div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <label className="text-sm">
            camera_id
            <input className="mt-1 w-full border rounded px-2 py-1" value={camera_id} onChange={e=>setCameraId(e.target.value)} />
          </label>
          <label className="text-sm">
            name
            <input className="mt-1 w-full border rounded px-2 py-1" value={name} onChange={e=>setName(e.target.value)} />
          </label>
          <label className="text-sm md:col-span-2">
            rtsp_url
            <input className="mt-1 w-full border rounded px-2 py-1" value={rtsp_url} onChange={e=>setUrl(e.target.value)} />
          </label>
          <label className="text-sm">
            fps (sampling)
            <input className="mt-1 w-full border rounded px-2 py-1" type="number" step="0.1" value={fps} onChange={e=>setFps(e.target.value)} />
          </label>
        </div>

        <div className="flex gap-2">
          <button className="px-3 py-2 rounded border" onClick={onSaveCamera}>Save camera</button>
          <button className="px-3 py-2 rounded bg-black text-white" onClick={onStart}>Start ingest</button>
        </div>
        <div className="text-xs text-gray-500">
          Start will enqueue a long-running worker task. Stop uses Redis flag; worker will stop within ~a few seconds.
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="font-semibold">Saved cameras</div>
        <button className="px-3 py-2 rounded border" onClick={refresh}>Refresh</button>
      </div>

      <div className="border rounded overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left p-2">camera_id</th>
              <th className="text-left p-2">name</th>
              <th className="text-left p-2">enabled</th>
              <th className="text-left p-2">action</th>
            </tr>
          </thead>
          <tbody>
            {cams.map(c => (
              <tr key={c.id} className="border-t">
                <td className="p-2 font-mono">{c.camera_id}</td>
                <td className="p-2">{c.name}</td>
                <td className="p-2">{String(c.enabled)}</td>
                <td className="p-2">
                  <button className="px-3 py-1 rounded border" onClick={() => onStop(c.camera_id)}>Stop</button>
                </td>
              </tr>
            ))}
            {!cams.length && <tr><td className="p-2 text-gray-500" colSpan="4">No cameras</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
