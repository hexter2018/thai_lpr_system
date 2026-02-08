import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { absImageUrl, deleteRead, listPending, verifyRead } from '../lib/api.js'
import { formatTemplate, th } from '../lib/i18n.js'

function confidenceClass(v) {
  if (v >= 0.95) return 'text-emerald-200 border-emerald-300/40 bg-emerald-500/10'
  if (v >= 0.85) return 'text-amber-200 border-amber-300/40 bg-amber-500/10'
  return 'text-rose-200 border-rose-300/40 bg-rose-500/10'
}

function isTypingTarget(target) {
  if (!target) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable
}

function useToastQueue() {
  const [toasts, setToasts] = useState([])

  const pushToast = useCallback((message, tone = 'info') => {
    const id = `${Date.now()}-${Math.random()}`
    setToasts((prev) => [...prev, { id, message, tone }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id))
    }, 2800)
  }, [])

  return { toasts, pushToast }
}

export default function Queue() {
  const copy = th.queue
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [lastRefresh, setLastRefresh] = useState(null)
  const refreshInterval = 10000 // 10 seconds
  const { toasts, pushToast } = useToastQueue()

  const refresh = useCallback(async () => {
    setErr('')
    setIsRefreshing(true)
    try {
      const r = await listPending(200)
      setRows(r)
      setLastRefresh(new Date())
    } catch (e) {
      setErr(String(e))
    } finally {
      setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(() => {
      refresh()
    }, refreshInterval)
    return () => clearInterval(timer)
  }, [refresh, refreshInterval])

  async function confirm(id) {
    setBusyId(id)
    try {
      await verifyRead(id, { action: 'confirm', user: 'reviewer' })
      await refresh()
      pushToast(copy.actionConfirmToast, 'success')
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
      pushToast(copy.actionSaveToast, 'success')
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
      pushToast(copy.actionDeleteToast, 'danger')
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="rounded-2xl border border-blue-300/20 bg-gradient-to-r from-blue-600/20 via-blue-500/10 to-cyan-500/10 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-slate-100">{copy.title}</h1>
            <div className="text-sm text-slate-200">{copy.subtitle}</div>
            <div className="mt-1 text-xs text-slate-400">
              {formatTemplate(copy.autoRefresh, { seconds: Math.round(refreshInterval / 1000) })}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-blue-200/30 bg-blue-500/10 px-3 py-1 text-xs text-blue-100">
              {formatTemplate(copy.pending, { count: rows.length })}
            </span>
            {lastRefresh && (
              <span className="rounded-full border border-blue-200/20 bg-slate-900/40 px-3 py-1 text-xs text-slate-200">
                {formatTemplate(copy.updated, {
                  time: lastRefresh.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' }),
                })}
              </span>
            )}
            <button className="btn-blue" onClick={refresh} disabled={isRefreshing}>
              {isRefreshing ? copy.refreshing : copy.refresh}
            </button>
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
            onToast={pushToast}
          />
        ))}
        {!rows.length && !err && (
          <div className="rounded-2xl border border-blue-300/20 bg-slate-900/50 p-10 text-center text-slate-300">
            {copy.empty}
          </div>
        )}
      </div>

      <ToastStack toasts={toasts} />
    </div>
  )
}

export function QueueItem({ r, busy, onConfirm, onCorrect, onDelete, onToast }) {
  const copy = th.queue
  const [t, setT] = useState(r.plate_text || '')
  const [p, setP] = useState(r.province || '')
  const [note, setNote] = useState('')
  const [highlightField, setHighlightField] = useState(null)
  const [lastChange, setLastChange] = useState(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [viewer, setViewer] = useState({ open: false, src: '', title: '' })
  const provinceMissing = !p.trim()

  // ✅ UPDATED: เพิ่ม Quick Fix buttons และจัดกลุ่ม
  const commonFixes = useMemo(
    () => [
      { from: 'ข', to: 'ฆ', label: 'ข→ฆ', desc: formatTemplate(copy.quickFixTooltip, { from: 'ข', to: 'ฆ' }), group: 'high' },
      { from: 'ฆ', to: 'ข', label: 'ฆ→ข', desc: formatTemplate(copy.quickFixTooltip, { from: 'ฆ', to: 'ข' }), group: 'high' },
      { from: 'ข', to: 'ม', label: 'ข→ม', desc: formatTemplate(copy.quickFixTooltip, { from: 'ข', to: 'ม' }), group: 'high' },
      { from: 'ม', to: 'ข', label: 'ม→ข', desc: formatTemplate(copy.quickFixTooltip, { from: 'ม', to: 'ข' }), group: 'high' },
      { from: 'ค', to: 'ฅ', label: 'ค→ฅ', desc: formatTemplate(copy.quickFixTooltip, { from: 'ค', to: 'ฅ' }), group: 'medium' },
      { from: 'ถ', to: 'ค', label: 'ถ→ค', desc: formatTemplate(copy.quickFixTooltip, { from: 'ถ', to: 'ค' }), group: 'medium' },
      { from: 'ศ', to: 'ส', label: 'ศ→ส', desc: formatTemplate(copy.quickFixTooltip, { from: 'ศ', to: 'ส' }), group: 'medium' },
      { from: 'ผ', to: 'พ', label: 'ผ→พ', desc: formatTemplate(copy.quickFixTooltip, { from: 'ผ', to: 'พ' }), group: 'medium' },
      { from: 'พ', to: 'ผ', label: 'พ→ผ', desc: formatTemplate(copy.quickFixTooltip, { from: 'พ', to: 'ผ' }), group: 'medium' },
      { from: 'บ', to: 'ป', label: 'บ→ป', desc: formatTemplate(copy.quickFixTooltip, { from: 'บ', to: 'ป' }), group: 'medium' },
      { from: 'ป', to: 'บ', label: 'ป→บ', desc: formatTemplate(copy.quickFixTooltip, { from: 'ป', to: 'บ' }), group: 'medium' },
    ],
    [copy.quickFixTooltip],
  )

  const highPriorityFixes = commonFixes.filter(f => f.group === 'high')
  const mediumPriorityFixes = commonFixes.filter(f => f.group === 'medium')

  const provinceShortcuts = useMemo(
    () => [
      { value: 'กรุงเทพมหานคร', label: 'กทม', icon: '🏙️' },
      { value: 'สมุทรปราการ', label: 'ปราการ', icon: '🏭' },
      { value: 'สมุทรสาคร', label: 'สาคร', icon: '⚓' },
      { value: 'นนทบุรี', label: 'นนท์', icon: '🏘️' },
      { value: 'ปทุมธานี', label: 'ปทุม', icon: '🌾' },
      { value: 'ชลบุรี', label: 'ชล', icon: '🏖️' },
    ],
    [],
  )

  useEffect(() => {
    if (!highlightField) return
    const timer = setTimeout(() => setHighlightField(null), 1600)
    return () => clearTimeout(timer)
  }, [highlightField])

  function setFieldChange(field, nextValue, label) {
    const previousValue = field === 'plate' ? t : p
    if (previousValue === nextValue) return
    setLastChange({ field, previousValue, nextValue, label })
    if (field === 'plate') {
      setT(nextValue)
    } else {
      setP(nextValue)
    }
    setHighlightField(field)
  }

  function applyFix(from, to) {
    const next = t.replace(new RegExp(from, 'g'), to)
    setFieldChange('plate', next, `${from}→${to}`)
  }

  function normalizePlateText(raw) {
    return (raw || '')
      .trim()
      .replace(/[\s\-.]/g, '')
      .replace(/[๐-๙]/g, (d) => '๐๑๒๓๔๕๖๗๘๙'.indexOf(d))
      .toUpperCase()
  }

  function handleNormalize() {
    const next = normalizePlateText(t)
    setFieldChange('plate', next, copy.normalize)
    onToast?.(copy.actionNormalizeToast, 'info')
  }

  function handleUndo() {
    if (!lastChange) return
    if (lastChange.field === 'plate') {
      setT(lastChange.previousValue)
    } else {
      setP(lastChange.previousValue)
    }
    setHighlightField(lastChange.field)
    setLastChange(null)
  }

  function handleKeyDown(e) {
    if (busy) return
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault()
      onCorrect(t, p, note)
      return
    }
    if (e.key === 'Enter' && !e.ctrlKey) {
      if (e.target.tagName === 'TEXTAREA') return
      e.preventDefault()
      onConfirm()
      return
    }
    if (!isTypingTarget(e.target)) {
      if (e.key === 'n' || e.key === 'N') {
        e.preventDefault()
        handleNormalize()
      }
      if (e.key === 'Delete') {
        e.preventDefault()
        setDeleteOpen(true)
      }
    }
  }

  function openViewer(src, title) {
    setViewer({ open: true, src, title })
  }

  return (
    <div className="rounded-2xl border border-blue-300/20 bg-slate-900/60 p-4 shadow-lg shadow-blue-950/10">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[620px_minmax(0,1fr)] 2xl:grid-cols-[680px_minmax(0,1fr)]">
        <div className="rounded-2xl border border-blue-300/15 bg-slate-950/40 p-4">
          <div className="flex items-center justify-between pb-2">
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-300">{copy.evidenceTitle}</div>
              <div className="text-xs text-slate-500">{copy.evidenceSubtitle}</div>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-slate-300">{copy.original}</div>
              <div className="relative">
                <img
                  className="h-44 w-full rounded-xl border border-blue-300/20 bg-slate-950/40 object-contain md:h-48"
                  src={absImageUrl(r.original_url)}
                  alt={copy.original}
                  onClick={() => openViewer(absImageUrl(r.original_url), copy.original)}
                />
                <button
                  type="button"
                  className="absolute right-2 top-2 rounded-lg border border-white/10 bg-slate-900/80 px-2 py-1 text-xs text-slate-100 hover:border-white/30"
                  onClick={() => openViewer(absImageUrl(r.original_url), copy.original)}
                >
                  ⛶ {copy.openFull}
                </button>
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-slate-300">{copy.cropPlate}</div>
              <div className="relative">
                <img
                  className="h-52 w-full rounded-xl border border-blue-300/20 bg-slate-950/40 object-contain md:h-60"
                  src={absImageUrl(r.crop_url)}
                  alt={copy.cropPlate}
                  onClick={() => openViewer(absImageUrl(r.crop_url), copy.cropPlate)}
                />
                <button
                  type="button"
                  className="absolute right-2 top-2 rounded-lg border border-white/10 bg-slate-900/80 px-2 py-1 text-xs text-slate-100 hover:border-white/30"
                  onClick={() => openViewer(absImageUrl(r.crop_url), copy.cropPlate)}
                >
                  ⛶ {copy.openFull}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="flex h-full flex-col" onKeyDown={handleKeyDown} tabIndex={0}>
          <div className="rounded-2xl border border-blue-300/20 bg-slate-950/70 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-base font-semibold text-slate-100">{copy.ocrTitle}</div>
                <div className="text-xs text-slate-400">{copy.ocrHint}</div>
              </div>
              
              {/* ✅ UPDATED: Visual Confidence Indicator */}
              <div className="space-y-2">
                <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${confidenceClass(r.confidence ?? 0)}`}>
                  {((r.confidence ?? 0) * 100).toFixed(1)}%
                </span>
                
                {/* Progress bar */}
                <div className="relative h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div 
                    className={`h-full transition-all duration-500 ${
                      (r.confidence ?? 0) >= 0.95 ? 'bg-emerald-500' :
                      (r.confidence ?? 0) >= 0.85 ? 'bg-amber-500' : 
                      (r.confidence ?? 0) >= 0.60 ? 'bg-orange-500' :
                      'bg-rose-500'
                    }`}
                    style={{ width: `${(r.confidence ?? 0) * 100}%` }}
                  />
                </div>
                
                {/* Indicators */}
                <div className="flex justify-between text-[10px]">
                  <span className="text-rose-400">ต่ำ</span>
                  <span className="text-amber-400">ปานกลาง</span>
                  <span className="text-emerald-400">สูง</span>
                </div>
                
                {/* Warning */}
                {(r.confidence ?? 0) < 0.6 && (
                  <div className="flex items-center gap-2 p-2 rounded-lg bg-rose-500/10 border border-rose-300/30">
                    <span className="text-rose-400">⚠️</span>
                    <span className="text-xs text-rose-200">ควรตรวจสอบอย่างละเอียด</span>
                  </div>
                )}
              </div>
            </div>
            <div className="mt-2 text-xs text-slate-500">{copy.shortcutsHint}</div>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <label className="text-base font-semibold text-slate-100">
              {copy.plate}
              <input
                className={`input-dark mt-2 text-lg font-semibold tracking-wide md:text-xl ${
                  highlightField === 'plate' ? 'ring-2 ring-blue-300/60' : ''
                }`}
                placeholder={copy.platePlaceholder}
                value={t}
                onChange={(e) => setT(e.target.value)}
              />

              {/* ✅ UPDATED: Grouped Quick Fix Buttons */}
              <div className="mt-3 space-y-2">
                {/* กลุ่มที่ 1: สับสนบ่อยสุด */}
                <div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className="w-1 h-3 bg-rose-400 rounded-full"></div>
                    <span className="text-xs text-slate-400 font-medium">สับสนบ่อย</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {highPriorityFixes.map((fix) => (
                      <button
                        key={fix.label}
                        type="button"
                        title={fix.desc}
                        className="min-h-[28px] rounded-lg border border-rose-300/40 bg-rose-500/10 px-2.5 py-1 text-xs text-rose-100 transition hover:bg-rose-500/20 hover:border-rose-300/60"
                        onClick={() => applyFix(fix.from, fix.to)}
                      >
                        {fix.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* กลุ่มที่ 2: อื่นๆ */}
                <div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className="w-1 h-3 bg-amber-400 rounded-full"></div>
                    <span className="text-xs text-slate-400 font-medium">อื่นๆ</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {mediumPriorityFixes.map((fix) => (
                      <button
                        key={fix.label}
                        type="button"
                        title={fix.desc}
                        className="min-h-[28px] rounded-lg border border-amber-300/40 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-100 transition hover:bg-amber-500/20 hover:border-amber-300/60"
                        onClick={() => applyFix(fix.from, fix.to)}
                      >
                        {fix.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </label>

            <label className="text-base font-semibold text-slate-100">
              {copy.province}
              <input
                className={`input-dark mt-2 text-lg font-semibold md:text-xl ${
                  provinceMissing ? 'border-amber-300/50 bg-amber-500/10' : ''
                } ${highlightField === 'province' ? 'ring-2 ring-blue-300/60' : ''}`}
                placeholder={copy.provincePlaceholder}
                value={p}
                onChange={(e) => setP(e.target.value)}
              />

              <div className="mt-3">
                <div className="text-xs text-slate-300">{copy.provinceHeading}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {provinceShortcuts.map((prov) => (
                    <button
                      key={prov.value}
                      type="button"
                      title={prov.value}
                      className="min-h-[34px] rounded-lg border border-blue-300/30 bg-slate-800/80 px-3 py-1 text-sm text-blue-100 transition hover:border-blue-300/60 hover:bg-blue-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/70"
                      onClick={() => setFieldChange('province', prov.value, prov.value)}
                    >
                      {prov.icon} {prov.label}
                    </button>
                  ))}
                </div>
              </div>

              {provinceMissing && <div className="mt-2 text-xs text-amber-200">{copy.provinceMissing}</div>}
            </label>
          </div>

          <label className="mt-4 text-base font-semibold text-slate-100">
            {copy.note}
            <input
              className="input-dark mt-2 text-lg md:text-xl"
              placeholder={copy.notePlaceholder}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>

          <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
            {lastChange ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-slate-300">{copy.undo}:</span>
                <span className="rounded-full border border-blue-300/30 bg-slate-900/70 px-2 py-0.5 text-slate-200">
                  {lastChange.label}
                </span>
                <button
                  type="button"
                  onClick={handleUndo}
                  className="rounded-full border border-blue-300/40 px-3 py-1 text-xs text-blue-100 hover:border-blue-300/70"
                >
                  {copy.undo}
                </button>
              </div>
            ) : (
              <span className="text-slate-500">{copy.shortcutsHint}</span>
            )}
          </div>

          <div className="sticky bottom-0 mt-4 flex flex-col gap-2 rounded-2xl border border-blue-300/20 bg-slate-900/90 p-3 shadow-lg shadow-blue-950/20 sm:flex-row sm:flex-wrap lg:flex-nowrap">
            <button
              disabled={busy}
              onClick={onConfirm}
              className="btn-blue w-full justify-center whitespace-nowrap disabled:opacity-50 sm:w-auto lg:flex-1"
            >
              {busy ? copy.loading : `✓ ${copy.confirm}`}
              <kbd className="ml-2 rounded bg-blue-700/50 px-1.5 py-0.5 text-xs font-mono">Enter</kbd>
            </button>
            <button
              disabled={busy}
              onClick={() => onCorrect(t, p, note)}
              className="btn-soft w-full justify-center whitespace-nowrap disabled:opacity-50 sm:w-auto lg:flex-1"
            >
              💾 {copy.saveCorrection}
              <kbd className="ml-2 rounded bg-slate-700 px-1.5 py-0.5 text-xs font-mono">Ctrl+Enter</kbd>
            </button>
            <button
              type="button"
              className="btn-soft w-full justify-center whitespace-nowrap sm:w-auto lg:flex-1"
              onClick={handleNormalize}
            >
              🔧 {copy.normalize}
            </button>
            <button
              type="button"
              className="w-full justify-center whitespace-nowrap rounded-xl border border-rose-300/60 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-100 transition hover:bg-rose-500/20 sm:w-auto lg:flex-1"
              disabled={busy}
              onClick={() => setDeleteOpen(true)}
            >
              🗑️ {copy.delete}
            </button>
          </div>
        </div>
      </div>

      <DeleteConfirmModal
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={() => {
          setDeleteOpen(false)
          onDelete()
        }}
        plate={t}
        province={p}
        confidence={(r.confidence ?? 0).toFixed(3)}
      />

      <ImageViewerModal
        open={viewer.open}
        src={viewer.src}
        title={viewer.title}
        onClose={() => setViewer({ open: false, src: '', title: '' })}
      />
    </div>
  )
}

function DeleteConfirmModal({ open, onClose, onConfirm, plate, province, confidence }) {
  const copy = th.queue
  const modalRef = useRef(null)

  useEffect(() => {
    if (!open) return
    function handleKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  useEffect(() => {
    if (open) {
      modalRef.current?.focus()
    }
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4">
      <div
        ref={modalRef}
        tabIndex={-1}
        className="w-full max-w-md rounded-2xl border border-rose-300/40 bg-slate-900 p-5 text-slate-100 shadow-xl"
      >
        <div className="text-lg font-semibold text-rose-100">{copy.deleteTitle}</div>
        <p className="mt-2 text-sm text-slate-300">{copy.deleteBody}</p>
        <div className="mt-4 rounded-xl border border-rose-300/30 bg-rose-500/5 p-3 text-sm">
          <div className="flex justify-between gap-3">
            <span className="text-slate-400">{copy.plate}</span>
            <span className="font-semibold text-slate-100">{plate || '-'}</span>
          </div>
          <div className="mt-2 flex justify-between gap-3">
            <span className="text-slate-400">{copy.province}</span>
            <span className="font-semibold text-slate-100">{province || '-'}</span>
          </div>
          <div className="mt-2 flex justify-between gap-3">
            <span className="text-slate-400">{copy.confidenceLabel}</span>
            <span className="font-semibold text-slate-100">{confidence}</span>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-xl border border-slate-500/40 px-4 py-2 text-sm text-slate-200 hover:border-slate-400/70"
            onClick={onClose}
          >
            {copy.deleteCancel}
          </button>
          <button
            type="button"
            className="rounded-xl border border-rose-300/60 bg-rose-500/20 px-4 py-2 text-sm font-semibold text-rose-100 hover:bg-rose-500/30"
            onClick={onConfirm}
          >
            {copy.deleteConfirm}
          </button>
        </div>
      </div>
    </div>
  )
}

function ImageViewerModal({ open, src, title, onClose }) {
  const [scale, setScale] = useState(1)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const dragState = useRef({ dragging: false, startX: 0, startY: 0, x: 0, y: 0 })

  useEffect(() => {
    if (!open) return
    function handleKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  useEffect(() => {
    if (open) {
      setScale(1)
      setPosition({ x: 0, y: 0 })
    }
  }, [open, src])

  if (!open) return null

  function onWheel(e) {
    e.preventDefault()
    const delta = e.deltaY * -0.001
    setScale((prev) => Math.min(4, Math.max(0.8, prev + delta)))
  }

  function onMouseDown(e) {
    dragState.current = {
      dragging: true,
      startX: e.clientX,
      startY: e.clientY,
      x: position.x,
      y: position.y,
    }
  }

  function onMouseMove(e) {
    if (!dragState.current.dragging) return
    const dx = e.clientX - dragState.current.startX
    const dy = e.clientY - dragState.current.startY
    setPosition({ x: dragState.current.x + dx, y: dragState.current.y + dy })
  }

  function onMouseUp() {
    dragState.current.dragging = false
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-950/90" onMouseMove={onMouseMove} onMouseUp={onMouseUp}>
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3 text-slate-100">
        <div className="text-sm font-semibold">{title}</div>
        <button
          type="button"
          className="rounded-lg border border-white/10 px-3 py-1 text-xs text-slate-200 hover:border-white/30"
          onClick={onClose}
        >
          {th.queue.close} · {th.queue.escHint}
        </button>
      </div>
      <div className="flex-1 overflow-hidden" onWheel={onWheel}>
        <div
          className="flex h-full w-full items-center justify-center"
          onMouseDown={onMouseDown}
          onMouseLeave={onMouseUp}
        >
          <img
            src={src}
            alt={title}
            className="max-h-[85vh] max-w-[90vw] select-none"
            style={{
              transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
              cursor: dragState.current.dragging ? 'grabbing' : 'grab',
            }}
            draggable={false}
          />
        </div>
      </div>
      <div className="border-t border-white/10 px-4 py-2 text-xs text-slate-300">
        {th.queue.imageViewerHint}
      </div>
    </div>
  )
}

function ToastStack({ toasts }) {
  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`rounded-xl border px-4 py-3 text-sm shadow-lg ${
            toast.tone === 'danger'
              ? 'border-rose-300/50 bg-rose-500/20 text-rose-100'
              : toast.tone === 'success'
                ? 'border-emerald-300/50 bg-emerald-500/20 text-emerald-100'
                : 'border-blue-300/40 bg-blue-500/10 text-blue-100'
          }`}
        >
          {toast.message}
        </div>
      ))}
    </div>
  )
}
