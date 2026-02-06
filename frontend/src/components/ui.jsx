import React from 'react'

export const Card = React.forwardRef(function Card({ children, className = '', ...props }, ref) {
  return (
    <div
      ref={ref}
      className={`rounded-2xl border border-blue-200/20 bg-slate-900/70 p-4 shadow-lg shadow-blue-950/20 ${className}`}
      {...props}
    >
      {children}
    </div>
  )
})

export function Button({ children, variant = 'primary', className = '', ...props }) {
  const base = 'inline-flex items-center justify-center rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50'
  const variants = {
    primary: 'bg-blue-600 text-white hover:bg-blue-500',
    secondary: 'border border-blue-200/30 bg-transparent text-blue-100 hover:bg-blue-500/15',
    danger: 'bg-rose-600 text-white hover:bg-rose-500',
  }
  return (
    <button className={`${base} ${variants[variant] || variants.primary} ${className}`} {...props}>
      {children}
    </button>
  )
}

export function Input({ className = '', ...props }) {
  return <input className={`mt-1 w-full rounded-xl border border-blue-200/25 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 ${className}`} {...props} />
}

export function Badge({ score = 0 }) {
  const cls = score >= 0.95
    ? 'border-emerald-300/40 bg-emerald-500/10 text-emerald-200'
    : score >= 0.85
      ? 'border-amber-300/40 bg-amber-500/10 text-amber-100'
      : 'border-rose-300/40 bg-rose-500/10 text-rose-200'
  return <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${cls}`}>{score.toFixed(3)}</span>
}

export function PageHeader({ title, subtitle, action }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-blue-200/20 bg-gradient-to-r from-blue-600/20 to-cyan-500/10 p-5">
      <div>
        <h2 className="text-2xl font-semibold text-slate-100">{title}</h2>
        {subtitle && <p className="text-sm text-slate-300">{subtitle}</p>}
      </div>
      {action ? <div>{action}</div> : null}
    </div>
  )
}
