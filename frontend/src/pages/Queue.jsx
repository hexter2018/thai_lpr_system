import React, { useEffect, useState } from 'react'
import { absImageUrl, deleteRead, listPending, verifyRead } from '../lib/api.js'

function confidenceClass(v) {
  if (v >= 0.95) return 'text-emerald-200 border-emerald-300/40 bg-emerald-500/10'
  if (v >= 0.85) return 'text-amber-200 border-amber-300/40 bg-amber-500/10'
  return 'text-rose-200 border-rose-300/40 bg-rose-500/10'
}

export default function Queue() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [busyId, setBusyId] = useState(null)

  async function refresh() {
    setErr('')
    try {
      const r = await listPending(200)
      setRows(r)
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function confirm(id) {
    setBusyId(id)
    try {
      await verifyRead(id, { action: 'confirm', user: 'reviewer' })
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  async function correct(id, corrected_text, corrected_province, note = '') {
    setBusyId(id)
    try {
      await verifyRead(id, { action: 'correct', corrected_text, corrected_province, note, user: 'reviewer' })
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  async function remove(id) {
    setBusyId(id)
    setErr('')
    try {
      await deleteRead(id)
      await refresh()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-blue-300/20 bg-gradient-to-r from-blue-600/20 to-cyan-500/10 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-slate-100">Verification Queue</h1>
            <div className="text-sm text-slate-300">ตรวจผล OCR และยืนยัน/แก้ไขก่อนบันทึกเข้า Master</div>
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-blue-200/30 bg-blue-500/10 px-3 py-1 text-xs text-blue-100">Pending {rows.length}</span>
            <button className="btn-blue" onClick={refresh}>Refresh</button>
          </div>
        </div>
      </div>

      {err && <div className="rounded-xl border border-rose-300/40 bg-rose-500/10 p-3 text-rose-200">{err}</div>}

      <div className="space-y-4">
        {rows.map((r) => (
          <QueueItem
            key={r.id}
            r={r}
            busy={busyId === r.id}
            onConfirm={() => confirm(r.id)}
            onCorrect={(t, p, n) => correct(r.id, t, p, n)}
            onDelete={() => remove(r.id)}
          />
        ))}
        {!rows.length && !err && <div className="rounded-2xl border border-blue-300/20 bg-slate-900/50 p-10 text-center text-slate-300">No pending items.</div>}
      </div>
    </div>
  )
}

function QueueItem({ r, busy, onConfirm, onCorrect, onDelete }) {
  const [t, setT] = useState(r.plate_text || '')
  const [p, setP] = useState(r.province || '')
  const [note, setNote] = useState('')
  const provinceMissing = !p.trim()

  // ✅ Quick Fix Buttons Configuration
  const commonFixes = [
    { from: 'ข', to: 'ฆ', label: 'ข→ฆ', desc: 'แก้ ข เป็น ฆ' },
    { from: 'ฆ', to: 'ข', label: 'ฆ→ข', desc: 'แก้ ฆ เป็น ข' },
    { from: 'ค', to: 'ฅ', label: 'ค→ฅ', desc: 'แก้ ค เป็น ฅ' },
    { from: 'ผ', to: 'พ', label: 'ผ→พ', desc: 'แก้ ผ เป็น พ' },
    { from: 'พ', to: 'ผ', label: 'พ→ผ', desc: 'แก้ พ เป็น ผ' },
    { from: 'บ', to: 'ป', label: 'บ→ป', desc: 'แก้ บ เป็น ป' },
    { from: 'ป', to: 'บ', label: 'ป→บ', desc: 'แก้ ป เป็น บ' },
  ]

  // ✅ Province Quick Fixes
  const provinceShortcuts = [
    { value: 'กรุงเทพมหานคร', label: 'กทม', icon: '🏙️' },
    { value: 'สมุทรปราการ', label: 'ปราการ', icon: '🏭' },
    { value: 'สมุทรสาคร', label: 'สาคร', icon: '⚓' },
    { value: 'นนทบุรี', label: 'นนท์', icon: '🏘️' },
    { value: 'ปทุมธานี', label: 'ปทุม', icon: '🌾' },
    { value: 'ชลบุรี', label: 'ชล', icon: '🏖️' },
  ]

  function applyFix(from, to) {
    setT(t.replace(new RegExp(from, 'g'), to))
  }

  function normalizePlateText(raw) {
    return (raw || '')
      .trim()
      .replace(/[\s\-.]/g, '')
      .replace(/[๐-๙]/g, (d) => '๐๑๒๓๔๕๖๗๘๙'.indexOf(d))
      .toUpperCase()
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.ctrlKey) {
      e.preventDefault()
      onConfirm()
    }
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault()
      onCorrect(t, p, note)
    }
  }

  return (
    <div className="rounded-2xl border border-blue-300/20 bg-slate-900/55 p-4 shadow-lg shadow-blue-950/10">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[560px_minmax(0,1fr)]">
        <div className="rounded-2xl border border-blue-300/15 bg-slate-950/40 p-3">
          <div className="flex items-center justify-between pb-2">
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-400">หลักฐานภาพ</div>
              <div className="text-xs text-slate-500">ดูภาพรวมและภาพป้ายเพื่อยืนยัน</div>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">Original</div>
              <img className="h-48 w-full rounded-xl border border-blue-300/20 bg-slate-950/40 object-contain" src={absImageUrl(r.original_url)} />
            </div>
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">Crop plate</div>
              <img className="h-48 w-full rounded-xl border border-blue-300/20 bg-slate-950/40 object-contain" src={absImageUrl(r.crop_url)} />
            </div>
          </div>
        </div>

        <div className="space-y-4" onKeyDown={onKeyDown} tabIndex={0}>
          <div className="rounded-2xl border border-blue-300/15 bg-slate-950/35 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm text-slate-300">ผล OCR</div>
                <div className="text-xs text-slate-500">Enter = ยืนยัน, Ctrl+Enter = บันทึกแก้ไข</div>
              </div>
              <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${confidenceClass(r.confidence ?? 0)}`}>
                {(r.confidence ?? 0).toFixed(3)}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <label className="text-sm font-semibold text-slate-200">
              Plate
              <input className="input-dark text-base md:text-lg" value={t} onChange={(e) => setT(e.target.value)} />

              <div className="mt-2">
                <div className="text-xs text-slate-400">Quick fix:</div>
                <div className="mt-1 flex flex-wrap gap-2">
                  {commonFixes.map((fix) => (
                    <button
                      key={fix.label}
                      type="button"
                      title={fix.desc}

                      className="rounded-lg border border-blue-300/20 bg-slate-800/80 px-2.5 py-1 text-xs text-blue-100 transition hover:bg-blue-500/20 hover:border-blue-400/40"

                      onClick={() => applyFix(fix.from, fix.to)}
                    >
                      {fix.label}
                    </button>
                  ))}
                </div>
              </div>
            </label>

            <label className="text-sm font-semibold text-slate-200">
              Province
              <input

                className={`input-dark text-base md:text-lg ${provinceMissing ? 'border-amber-300/50 bg-amber-500/5' : ''}`}


                placeholder="ยังอ่านจังหวัดไม่ได้"
                value={p}
                onChange={(e) => setP(e.target.value)}
              />

              <div className="mt-2">
                <div className="text-xs text-slate-400">Quick:</div>

                <div className="mt-1 flex flex-wrap gap-2">

                  {provinceShortcuts.map((prov) => (
                    <button
                      key={prov.value}
                      type="button"
                      title={prov.value}

                      className="rounded-lg border border-blue-300/20 bg-slate-800/80 px-2.5 py-1 text-xs text-blue-100 transition hover:bg-blue-500/20 hover:border-blue-400/40"

                      onClick={() => setP(prov.value)}
                    >
                      {prov.icon} {prov.label}
                    </button>
                  ))}
                </div>
              </div>

              {provinceMissing && <div className="mt-1 text-xs text-amber-200">ยังอ่านจังหวัดไม่ได้ - สามารถยืนยันหรือแก้ไขได้</div>}
            </label>
          </div>

          <label className="text-sm font-semibold text-slate-200">
            Note
            <input

              className="input-dark text-base md:text-lg"


              placeholder="ระบุหมายเหตุเพิ่มเติม (ถ้ามี)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>


          <div className="grid grid-cols-1 gap-2 rounded-2xl border border-blue-300/15 bg-slate-950/35 p-3 sm:grid-cols-2 lg:grid-cols-4">
            <button disabled={busy} onClick={onConfirm} className="btn-blue w-full justify-center disabled:opacity-50">
              ✓ Confirm
              <kbd className="ml-1 rounded bg-blue-700/50 px-1.5 py-0.5 text-xs font-mono">Enter</kbd>
            </button>
            <button disabled={busy} onClick={() => onCorrect(t, p, note)} className="btn-soft w-full justify-center disabled:opacity-50">

              💾 Save correction
              <kbd className="ml-1 rounded bg-slate-700 px-1.5 py-0.5 text-xs font-mono">Ctrl+Enter</kbd>
            </button>
            <button type="button" className="btn-soft w-full justify-center" onClick={() => setT(normalizePlateText(t))}>
              🔧 Normalize
            </button>
            <button
              type="button"
              className="btn-soft w-full justify-center border border-rose-300/40 text-rose-200 hover:border-rose-300/70"
              disabled={busy}
              onClick={() => {
                if (window.confirm('ลบรายการนี้ออกจากคิวตรวจสอบใช่หรือไม่?')) {
                  onDelete()
                }
              }}
            >
              🗑️ Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
