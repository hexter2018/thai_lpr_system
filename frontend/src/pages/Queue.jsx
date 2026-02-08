import React, { useCallback, useEffect, useState, useRef } from 'react'
import { absImageUrl, deleteRead, listPending, verifyRead } from '../lib/api.js'
import { 
  Button, 
  Card, 
  CardHeader, 
  CardBody,
  Input, 
  Badge, 
  ConfidenceBadge, 
  Toast, 
  Modal,
  EmptyState,
  Spinner 
} from '../components/UIComponents.jsx'

/* ===== PROVINCES DATA ===== */
const POPULAR_PROVINCES = [
  { value: 'กรุงเทพมหานคร', label: 'กทม', icon: '🏙️' },
  { value: 'สมุทรปราการ', label: 'ปราการ', icon: '🏭' },
  { value: 'สมุทรสาคร', label: 'สาคร', icon: '⚓' },
  { value: 'นนทบุรี', label: 'นนท์', icon: '🏘️' },
  { value: 'ปทุมธานี', label: 'ปทุม', icon: '🌾' },
  { value: 'ชลบุรี', label: 'ชล', icon: '🏖️' }
]

/* ===== CONFUSABLE CHARACTER FIXES ===== */
const CONFUSION_FIXES = {
  high: [
    { from: 'ข', to: 'ฆ', tooltip: 'ข เป็น ฆ (สับสนบ่อย)' },
    { from: 'ฆ', to: 'ข', tooltip: 'ฆ เป็น ข (สับสนบ่อย)' },
    { from: 'ข', to: 'ม', tooltip: 'ข เป็น ม (สับสนบ่อย)' },
    { from: 'ม', to: 'ข', tooltip: 'ม เป็น ข (สับสนบ่อย)' }
  ],
  medium: [
    { from: 'ค', to: 'ฅ', tooltip: 'ค เป็น ฅ' },
    { from: 'ถ', to: 'ค', tooltip: 'ถ เป็น ค' },
    { from: 'ศ', to: 'ส', tooltip: 'ศ เป็น ส' },
    { from: 'ผ', to: 'พ', tooltip: 'ผ เป็น พ' },
    { from: 'พ', to: 'ผ', tooltip: 'พ เป็น ผ' },
    { from: 'บ', to: 'ป', tooltip: 'บ เป็น ป' },
    { from: 'ป', to: 'บ', tooltip: 'ป เป็น บ' }
  ]
}

/* ===== TOAST CONTAINER ===== */
function ToastContainer({ toasts }) {
  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 max-w-md">
      {toasts.map(toast => (
        <Toast 
          key={toast.id} 
          message={toast.message} 
          type={toast.type}
        />
      ))}
    </div>
  )
}

/* ===== IMAGE VIEWER MODAL ===== */
function ImageViewer({ open, src, title, onClose }) {
  const [scale, setScale] = useState(1)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const dragState = useRef({ dragging: false, startX: 0, startY: 0, x: 0, y: 0 })

  useEffect(() => {
    if (!open) return
    
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key === '+' || e.key === '=') setScale(s => Math.min(4, s + 0.2))
      if (e.key === '-') setScale(s => Math.max(0.5, s - 0.2))
      if (e.key === '0') { setScale(1); setPosition({ x: 0, y: 0 }) }
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

  const handleWheel = (e) => {
    e.preventDefault()
    const delta = e.deltaY * -0.001
    setScale(s => Math.min(4, Math.max(0.5, s + delta)))
  }

  const handleMouseDown = (e) => {
    dragState.current = {
      dragging: true,
      startX: e.clientX,
      startY: e.clientY,
      x: position.x,
      y: position.y
    }
  }

  const handleMouseMove = (e) => {
    if (!dragState.current.dragging) return
    const dx = e.clientX - dragState.current.startX
    const dy = e.clientY - dragState.current.startY
    setPosition({ x: dragState.current.x + dx, y: dragState.current.y + dy })
  }

  const handleMouseUp = () => {
    dragState.current.dragging = false
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex flex-col bg-slate-950/95 backdrop-blur-sm"
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-700/50 px-6 py-4 bg-slate-900/50">
        <div>
          <h3 className="text-lg font-semibold text-slate-100">{title}</h3>
          <p className="text-xs text-slate-400 mt-1">
            Zoom: {(scale * 100).toFixed(0)}% • คลิกค้างและลากเพื่อเลื่อน • เลื่อนล้อเมาส์เพื่อซูม
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setScale(s => Math.max(0.5, s - 0.2))}>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
            </svg>
          </Button>
          <Badge variant="default" size="sm">{(scale * 100).toFixed(0)}%</Badge>
          <Button variant="ghost" size="sm" onClick={() => setScale(s => Math.min(4, s + 0.2))}>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </Button>
          <div className="w-px h-6 bg-slate-700/50 mx-2" />
          <Button variant="ghost" size="sm" onClick={onClose}>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            ปิด (Esc)
          </Button>
        </div>
      </div>

      {/* Image Container */}
      <div className="flex-1 overflow-hidden" onWheel={handleWheel}>
        <div className="flex h-full w-full items-center justify-center p-8">
          <img
            src={src}
            alt={title}
            className="max-h-full max-w-full select-none shadow-2xl rounded-lg"
            style={{
              transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
              cursor: dragState.current.dragging ? 'grabbing' : 'grab',
              transition: dragState.current.dragging ? 'none' : 'transform 0.1s ease-out'
            }}
            onMouseDown={handleMouseDown}
            draggable={false}
          />
        </div>
      </div>
    </div>
  )
}

/* ===== DELETE CONFIRMATION MODAL ===== */
function DeleteConfirmModal({ open, onClose, onConfirm, plate, province, confidence }) {
  if (!open) return null

  return (
    <Modal open={open} onClose={onClose} title="ยืนยันการลบรายการ" size="sm">
      <div className="space-y-4">
        <p className="text-sm text-slate-300">
          โปรดยืนยันการลบรายการต่อไปนี้จากคิวตรวจสอบ
        </p>
        
        <Card className="bg-rose-500/5 border-rose-300/30">
          <CardBody className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">ป้ายทะเบียน</span>
              <span className="font-semibold text-slate-100">{plate || '-'}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">จังหวัด</span>
              <span className="font-semibold text-slate-100">{province || '-'}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">ความมั่นใจ</span>
              <span className="font-semibold text-slate-100">{confidence}</span>
            </div>
          </CardBody>
        </Card>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            ยกเลิก
          </Button>
          <Button variant="danger" onClick={onConfirm}>
            ยืนยันการลบ
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/* ===== VERIFICATION ITEM ===== */
function VerificationItem({ item, busy, onConfirm, onCorrect, onDelete, onToast }) {
  const [plateText, setPlateText] = useState(item.plate_text || '')
  const [province, setProvince] = useState(item.province || '')
  const [note, setNote] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [viewerOpen, setViewerOpen] = useState(false)
  const [viewerSrc, setViewerSrc] = useState('')
  const [viewerTitle, setViewerTitle] = useState('')
  const [lastChange, setLastChange] = useState(null)
  const [highlightField, setHighlightField] = useState(null)

  const provinceMissing = !province.trim()

  useEffect(() => {
    if (!highlightField) return
    const timer = setTimeout(() => setHighlightField(null), 1600)
    return () => clearTimeout(timer)
  }, [highlightField])

  const handleKeyDown = useCallback((e) => {
    if (busy) return
    
    const isTyping = ['INPUT', 'TEXTAREA'].includes(e.target.tagName)
    
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault()
      onCorrect(plateText, province, note)
    } else if (e.key === 'Enter' && !e.ctrlKey && !isTyping) {
      e.preventDefault()
      onConfirm()
    } else if (e.key === 'Delete' && !isTyping) {
      e.preventDefault()
      setDeleteOpen(true)
    } else if ((e.key === 'n' || e.key === 'N') && !isTyping) {
      e.preventDefault()
      handleNormalize()
    }
  }, [busy, plateText, province, note, onConfirm, onCorrect])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  const applyFix = (from, to) => {
    const next = plateText.replace(new RegExp(from, 'g'), to)
    setLastChange({ field: 'plate', from, to, prev: plateText })
    setPlateText(next)
    setHighlightField('plate')
    onToast?.(`แทนที่ ${from} → ${to}`, 'info')
  }

  const handleNormalize = () => {
    const normalized = plateText
      .trim()
      .replace(/[\s\-.]/g, '')
      .replace(/[๐-๙]/g, (d) => '๐๑๒๓๔๕๖๗๘๙'.indexOf(d))
      .toUpperCase()
    setLastChange({ field: 'plate', prev: plateText })
    setPlateText(normalized)
    setHighlightField('plate')
    onToast?.('จัดรูปแบบป้ายทะเบียนแล้ว', 'info')
  }

  const handleUndo = () => {
    if (!lastChange) return
    if (lastChange.field === 'plate') {
      setPlateText(lastChange.prev)
      setHighlightField('plate')
    }
    setLastChange(null)
  }

  const openViewer = (src, title) => {
    setViewerSrc(src)
    setViewerTitle(title)
    setViewerOpen(true)
  }

  return (
    <>
      <Card className="p-5">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[600px_minmax(0,1fr)]">
          {/* Left: Image Evidence */}
          <div>
            <CardHeader className="px-0 pt-0">
              <h3 className="text-sm font-semibold text-slate-100">หลักฐานภาพ</h3>
              <p className="text-xs text-slate-400 mt-0.5">ดูภาพรวมและภาพป้ายเพื่อยืนยัน</p>
            </CardHeader>
            
            <div className="grid grid-cols-2 gap-4 mt-4">
              {/* Original Image */}
              <div>
                <div className="text-xs font-medium text-slate-400 mb-2">ภาพต้นฉบับ</div>
                <div 
                  className="relative group cursor-pointer rounded-xl overflow-hidden border border-blue-300/20 hover:border-blue-400/40 transition-colors"
                  onClick={() => openViewer(absImageUrl(item.original_url), 'ภาพต้นฉบับ')}
                >
                  <img
                    src={absImageUrl(item.original_url)}
                    alt="Original"
                    className="w-full h-44 object-contain bg-slate-950/40"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-slate-950/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end justify-center pb-3">
                    <Badge variant="primary" size="sm">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                      </svg>
                      คลิกเพื่อดูขนาดเต็ม
                    </Badge>
                  </div>
                </div>
              </div>

              {/* Cropped Plate */}
              <div>
                <div className="text-xs font-medium text-slate-400 mb-2">ภาพป้ายที่ตัดออก</div>
                <div 
                  className="relative group cursor-pointer rounded-xl overflow-hidden border border-blue-300/20 hover:border-blue-400/40 transition-colors"
                  onClick={() => openViewer(absImageUrl(item.crop_url), 'ภาพป้ายที่ตัดออก')}
                >
                  <img
                    src={absImageUrl(item.crop_url)}
                    alt="Cropped Plate"
                    className="w-full h-44 object-contain bg-slate-950/40"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-slate-950/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end justify-center pb-3">
                    <Badge variant="primary" size="sm">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                      </svg>
                      คลิกเพื่อดูขนาดเต็ม
                    </Badge>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right: Form & Actions */}
          <div className="flex flex-col">
            <CardHeader className="px-0 pt-0 pb-4">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-slate-100">ผล OCR และการตรวจสอบ</h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Enter = ยืนยัน • Ctrl+Enter = บันทึกการแก้ไข • N = จัดรูปแบบ • Delete = ลบ
                  </p>
                </div>
                <ConfidenceBadge score={item.confidence || 0} />
              </div>
            </CardHeader>

            {/* Plate Input */}
            <div className="space-y-4">
              <Input
                label="ป้ายทะเบียน"
                value={plateText}
                onChange={(e) => setPlateText(e.target.value)}
                placeholder="กรอก/แก้ไขป้ายทะเบียน"
                className={`text-lg font-semibold tracking-wide ${highlightField === 'plate' ? 'ring-2 ring-blue-400' : ''}`}
              />

              {/* Quick Fix Buttons */}
              <div className="space-y-3">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-1 h-3 bg-rose-400 rounded-full" />
                    <span className="text-xs font-medium text-slate-400">สับสนบ่อย</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {CONFUSION_FIXES.high.map(fix => (
                      <button
                        key={`${fix.from}-${fix.to}`}
                        type="button"
                        title={fix.tooltip}
                        onClick={() => applyFix(fix.from, fix.to)}
                        className="px-2.5 py-1 text-xs font-medium rounded-lg border border-rose-300/40 bg-rose-500/10 text-rose-100 hover:bg-rose-500/20 hover:border-rose-300/60 transition-colors"
                      >
                        {fix.from}→{fix.to}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-1 h-3 bg-amber-400 rounded-full" />
                    <span className="text-xs font-medium text-slate-400">อื่นๆ</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {CONFUSION_FIXES.medium.map(fix => (
                      <button
                        key={`${fix.from}-${fix.to}`}
                        type="button"
                        title={fix.tooltip}
                        onClick={() => applyFix(fix.from, fix.to)}
                        className="px-2.5 py-1 text-xs font-medium rounded-lg border border-amber-300/40 bg-amber-500/10 text-amber-100 hover:bg-amber-500/20 hover:border-amber-300/60 transition-colors"
                      >
                        {fix.from}→{fix.to}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Province Input */}
              <Input
                label="จังหวัด"
                value={province}
                onChange={(e) => setProvince(e.target.value)}
                placeholder="ระบุจังหวัด"
                className={`text-lg font-semibold ${provinceMissing ? 'border-amber-400/50 bg-amber-500/5' : ''} ${highlightField === 'province' ? 'ring-2 ring-blue-400' : ''}`}
                hint={provinceMissing ? 'ยังอ่านจังหวัดไม่ได้ - สามารถยืนยันหรือแก้ไขได้' : undefined}
              />

              {/* Province Quick Select */}
              <div>
                <div className="text-xs font-medium text-slate-400 mb-2">จังหวัดยอดนิยม</div>
                <div className="flex flex-wrap gap-2">
                  {POPULAR_PROVINCES.map(prov => (
                    <button
                      key={prov.value}
                      type="button"
                      onClick={() => { setProvince(prov.value); setHighlightField('province') }}
                      className="px-3 py-1.5 text-sm font-medium rounded-lg border border-blue-300/30 bg-slate-800/80 text-blue-100 hover:bg-blue-500/20 hover:border-blue-300/60 transition-colors"
                    >
                      {prov.icon} {prov.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Note */}
              <Input
                label="หมายเหตุ (ถ้ามี)"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="ระบุหมายเหตุเพิ่มเติม"
              />

              {/* Undo */}
              {lastChange && (
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <span>การเปลี่ยนแปลงล่าสุด:</span>
                  <Badge variant="default" size="sm">
                    {lastChange.from ? `${lastChange.from}→${lastChange.to}` : 'จัดรูปแบบ'}
                  </Badge>
                  <button
                    onClick={handleUndo}
                    className="text-blue-400 hover:text-blue-300 font-medium"
                  >
                    เลิกทำ
                  </button>
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className="mt-6 pt-4 border-t border-slate-700/50">
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="primary"
                  disabled={busy}
                  onClick={onConfirm}
                  className="flex-1"
                  icon={
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  }
                >
                  ยืนยัน
                  <kbd className="ml-2 px-1.5 py-0.5 text-xs font-mono bg-blue-700/50 rounded">Enter</kbd>
                </Button>
                
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => onCorrect(plateText, province, note)}
                  className="flex-1"
                  icon={
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                      <path d="M7.707 10.293a1 1 0 10-1.414 1.414l3 3a1 1 0 001.414 0l3-3a1 1 0 00-1.414-1.414L11 11.586V6h5a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V8a2 2 0 012-2h5v5.586l-1.293-1.293zM9 4a1 1 0 012 0v2H9V4z" />
                    </svg>
                  }
                >
                  บันทึกการแก้ไข
                  <kbd className="ml-2 px-1.5 py-0.5 text-xs font-mono bg-slate-700 rounded">Ctrl+Enter</kbd>
                </Button>
                
                <Button
                  variant="secondary"
                  onClick={handleNormalize}
                  icon={
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clipRule="evenodd" />
                    </svg>
                  }
                >
                  จัดรูปแบบ
                </Button>

                <Button
                  variant="danger"
                  disabled={busy}
                  onClick={() => setDeleteOpen(true)}
                  icon={
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                    </svg>
                  }
                >
                  ลบ
                </Button>
              </div>
            </div>
          </div>
        </div>
      </Card>

      <DeleteConfirmModal
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={() => {
          setDeleteOpen(false)
          onDelete()
        }}
        plate={plateText}
        province={province}
        confidence={(item.confidence * 100).toFixed(1) + '%'}
      />

      <ImageViewer
        open={viewerOpen}
        src={viewerSrc}
        title={viewerTitle}
        onClose={() => setViewerOpen(false)}
      />
    </>
  )
}

/* ===== MAIN QUEUE PAGE ===== */
export default function Queue() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [toasts, setToasts] = useState([])
  const [lastRefresh, setLastRefresh] = useState(null)

  const addToast = useCallback((message, type = 'info') => {
    const id = Date.now()
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 3000)
  }, [])

  const refresh = useCallback(async () => {
    setError('')
    setLoading(true)
    try {
      const data = await listPending(200)
      setItems(data)
      setLastRefresh(new Date())
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 10000)
    return () => clearInterval(interval)
  }, [refresh])

  const handleConfirm = useCallback(async (id) => {
    setBusyId(id)
    try {
      await verifyRead(id, { action: 'confirm', user: 'reviewer' })
      await refresh()
      addToast('ยืนยันเรียบร้อยแล้ว', 'success')
    } catch (e) {
      setError(String(e))
    } finally {
      setBusyId(null)
    }
  }, [refresh, addToast])

  const handleCorrect = useCallback(async (id, corrected_text, corrected_province, note) => {
    setBusyId(id)
    try {
      await verifyRead(id, { action: 'correct', corrected_text, corrected_province, note, user: 'reviewer' })
      await refresh()
      addToast('บันทึกการแก้ไขแล้ว', 'success')
    } catch (e) {
      setError(String(e))
    } finally {
      setBusyId(null)
    }
  }, [refresh, addToast])

  const handleDelete = useCallback(async (id) => {
    setBusyId(id)
    try {
      await deleteRead(id)
      await refresh()
      addToast('ลบรายการแล้ว', 'success')
    } catch (e) {
      setError(String(e))
    } finally {
      setBusyId(null)
    }
  }, [refresh, addToast])

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      {/* Header */}
      <Card className="bg-gradient-to-r from-blue-600/20 via-blue-500/10 to-cyan-500/10">
        <CardBody>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-slate-100">คิวตรวจสอบ</h1>
              <p className="text-sm text-slate-300 mt-1">
                ตรวจผล OCR และยืนยัน/แก้ไขก่อนบันทึกเข้า Master
              </p>
              <p className="text-xs text-slate-400 mt-1">
                รีเฟรชอัตโนมัติทุก 10 วินาที
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Badge variant="primary" size="lg">
                รอการตรวจสอบ {items.length}
              </Badge>
              {lastRefresh && (
                <Badge variant="default" size="sm">
                  อัปเดต {lastRefresh.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })}
                </Badge>
              )}
              <Button
                variant="secondary"
                size="sm"
                onClick={refresh}
                disabled={loading}
                icon={loading ? <Spinner size="sm" /> : (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                )}
              >
                {loading ? 'กำลังรีเฟรช...' : 'รีเฟรช'}
              </Button>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* Error */}
      {error && (
        <Card className="bg-rose-500/10 border-rose-300/40">
          <CardBody>
            <div className="flex items-start gap-3">
              <svg className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
              <p className="text-sm text-rose-200">{error}</p>
            </div>
          </CardBody>
        </Card>
      )}

      {/* Items */}
      {loading && items.length === 0 ? (
        <Card>
          <CardBody>
            <div className="flex items-center justify-center py-12">
              <Spinner size="lg" className="text-blue-500" />
              <span className="ml-3 text-slate-300">กำลังโหลดข้อมูล...</span>
            </div>
          </CardBody>
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              icon="✓"
              title="ไม่มีรายการที่รอการตรวจสอบ"
              description="คิวว่างเปล่า - ทุกรายการได้รับการตรวจสอบแล้ว"
            />
          </CardBody>
        </Card>
      ) : (
        <div className="space-y-4">
          {items.map(item => (
            <VerificationItem
              key={item.id}
              item={item}
              busy={busyId === item.id}
              onConfirm={() => handleConfirm(item.id)}
              onCorrect={(text, prov, note) => handleCorrect(item.id, text, prov, note)}
              onDelete={() => handleDelete(item.id)}
              onToast={addToast}
            />
          ))}
        </div>
      )}

      <ToastContainer toasts={toasts} />
    </div>
  )
}
