import React from 'react'

/* ===== BUTTONS ===== */
export function Button({ 
  children, 
  variant = 'primary', 
  size = 'md',
  loading = false,
  disabled = false,
  icon,
  className = '', 
  ...props 
}) {
  const baseStyles = 'inline-flex items-center justify-center gap-2 font-semibold transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-slate-950'
  
  const variants = {
    primary: 'bg-gradient-to-r from-blue-600 to-blue-500 text-white hover:from-blue-500 hover:to-blue-400 shadow-lg shadow-blue-500/20 focus:ring-blue-500',
    secondary: 'bg-slate-800 text-slate-100 border border-blue-300/20 hover:bg-blue-500/10 hover:border-blue-300/40 focus:ring-blue-500',
    success: 'bg-gradient-to-r from-emerald-600 to-emerald-500 text-white hover:from-emerald-500 hover:to-emerald-400 shadow-lg shadow-emerald-500/20 focus:ring-emerald-500',
    danger: 'bg-gradient-to-r from-rose-600 to-rose-500 text-white hover:from-rose-500 hover:to-rose-400 shadow-lg shadow-rose-500/20 focus:ring-rose-500',
    ghost: 'text-slate-300 hover:bg-slate-800 focus:ring-slate-500'
  }
  
  const sizes = {
    sm: 'px-3 py-1.5 text-sm rounded-lg',
    md: 'px-4 py-2 text-sm rounded-xl',
    lg: 'px-6 py-3 text-base rounded-xl'
  }
  
  return (
    <button 
      className={`${baseStyles} ${variants[variant]} ${sizes[size]} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
      )}
      {icon && <span className="flex-shrink-0">{icon}</span>}
      {children}
    </button>
  )
}

/* ===== CARDS ===== */
export function Card({ children, className = '', hover = false, ...props }) {
  return (
    <div 
      className={`rounded-2xl border border-slate-700/50 bg-slate-900/70 shadow-lg ${hover ? 'hover:border-blue-300/30 hover:shadow-xl hover:shadow-blue-500/10 transition-all' : ''} ${className}`}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ children, className = '' }) {
  return (
    <div className={`px-5 py-4 border-b border-slate-700/50 ${className}`}>
      {children}
    </div>
  )
}

export function CardBody({ children, className = '' }) {
  return (
    <div className={`p-5 ${className}`}>
      {children}
    </div>
  )
}

/* ===== INPUTS ===== */
export function Input({ 
  label, 
  error, 
  hint,
  icon,
  className = '',
  containerClassName = '',
  ...props 
}) {
  return (
    <div className={containerClassName}>
      {label && (
        <label className="block text-sm font-medium text-slate-300 mb-2">
          {label}
        </label>
      )}
      <div className="relative">
        {icon && (
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
            {icon}
          </div>
        )}
        <input
          className={`
            w-full rounded-xl border bg-slate-950/50 px-4 py-2.5 text-sm text-slate-100
            transition-colors
            ${icon ? 'pl-10' : ''}
            ${error 
              ? 'border-rose-500/50 focus:border-rose-500 focus:ring-2 focus:ring-rose-500/20' 
              : 'border-blue-300/20 focus:border-blue-400/50 focus:ring-2 focus:ring-blue-400/20'
            }
            disabled:opacity-50 disabled:cursor-not-allowed
            placeholder:text-slate-500
            ${className}
          `}
          {...props}
        />
      </div>
      {error && (
        <p className="mt-1.5 text-xs text-rose-400 flex items-center gap-1">
          <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          {error}
        </p>
      )}
      {hint && !error && (
        <p className="mt-1.5 text-xs text-slate-400">
          {hint}
        </p>
      )}
    </div>
  )
}

/* ===== BADGES ===== */
export function Badge({ 
  children, 
  variant = 'default',
  size = 'md',
  className = '' 
}) {
  const variants = {
    default: 'bg-slate-800 text-slate-300 border-slate-700',
    primary: 'bg-blue-500/10 text-blue-300 border-blue-300/40',
    success: 'bg-emerald-500/10 text-emerald-300 border-emerald-300/40',
    warning: 'bg-amber-500/10 text-amber-300 border-amber-300/40',
    danger: 'bg-rose-500/10 text-rose-300 border-rose-300/40'
  }
  
  const sizes = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-1 text-xs',
    lg: 'px-3 py-1.5 text-sm'
  }
  
  return (
    <span className={`inline-flex items-center rounded-full border font-semibold ${variants[variant]} ${sizes[size]} ${className}`}>
      {children}
    </span>
  )
}

/* ===== CONFIDENCE BADGE ===== */
export function ConfidenceBadge({ score }) {
  const getVariant = () => {
    if (score >= 0.95) return { variant: 'success', label: 'สูงมาก', icon: '✓' }
    if (score >= 0.85) return { variant: 'success', label: 'สูง', icon: '✓' }
    if (score >= 0.70) return { variant: 'warning', label: 'ปานกลาง', icon: '!' }
    return { variant: 'danger', label: 'ต่ำ', icon: '⚠' }
  }
  
  const { variant, label, icon } = getVariant()
  
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Badge variant={variant} size="md">
          {icon} {label}
        </Badge>
        <span className="text-sm font-semibold text-slate-100">
          {(score * 100).toFixed(1)}%
        </span>
      </div>
      <ConfidenceBar score={score} />
    </div>
  )
}

/* ===== CONFIDENCE BAR ===== */
export function ConfidenceBar({ score }) {
  const getColor = () => {
    if (score >= 0.95) return 'bg-emerald-500'
    if (score >= 0.85) return 'bg-emerald-400'
    if (score >= 0.70) return 'bg-amber-500'
    if (score >= 0.60) return 'bg-orange-500'
    return 'bg-rose-500'
  }
  
  return (
    <div className="relative h-2 bg-slate-800 rounded-full overflow-hidden">
      {/* Threshold markers */}
      <div className="absolute inset-0 flex">
        <div className="w-[60%] border-r border-slate-700/50" />
        <div className="w-[25%] border-r border-slate-700/50" />
        <div className="w-[10%] border-r border-slate-700/50" />
      </div>
      
      {/* Progress bar */}
      <div 
        className={`h-full transition-all duration-500 ${getColor()}`}
        style={{ width: `${score * 100}%` }}
      />
    </div>
  )
}

/* ===== LOADING SPINNER ===== */
export function Spinner({ size = 'md', className = '' }) {
  const sizes = {
    sm: 'h-4 w-4',
    md: 'h-6 w-6',
    lg: 'h-8 w-8'
  }
  
  return (
    <svg className={`animate-spin ${sizes[size]} ${className}`} viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
    </svg>
  )
}

/* ===== TOAST NOTIFICATION ===== */
export function Toast({ message, type = 'info', onClose }) {
  const types = {
    success: {
      bg: 'bg-emerald-500/20 border-emerald-300/50',
      text: 'text-emerald-100',
      icon: (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
        </svg>
      )
    },
    error: {
      bg: 'bg-rose-500/20 border-rose-300/50',
      text: 'text-rose-100',
      icon: (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
        </svg>
      )
    },
    info: {
      bg: 'bg-blue-500/20 border-blue-300/50',
      text: 'text-blue-100',
      icon: (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
        </svg>
      )
    }
  }
  
  const config = types[type]
  
  return (
    <div 
      className={`flex items-start gap-3 rounded-xl border px-4 py-3 shadow-lg animate-[slideInRight_0.3s_ease-out] ${config.bg} ${config.text}`}
    >
      <div className="flex-shrink-0 mt-0.5">
        {config.icon}
      </div>
      <div className="flex-1 text-sm font-medium">
        {message}
      </div>
      {onClose && (
        <button
          onClick={onClose}
          className="flex-shrink-0 text-current opacity-70 hover:opacity-100 transition-opacity"
        >
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        </button>
      )}
    </div>
  )
}

/* ===== MODAL ===== */
export function Modal({ open, onClose, title, children, size = 'md' }) {
  if (!open) return null
  
  const sizes = {
    sm: 'max-w-md',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl'
  }
  
  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]"
      onClick={onClose}
    >
      <div 
        className={`w-full ${sizes[size]} rounded-2xl border border-slate-700/50 bg-slate-900 shadow-2xl animate-[slideInUp_0.3s_ease-out]`}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
            <h3 className="text-lg font-semibold text-slate-100">{title}</h3>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-slate-100 transition-colors"
            >
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </button>
          </div>
        )}
        <div className="p-6">
          {children}
        </div>
      </div>
    </div>
  )
}

/* ===== STAT CARD ===== */
export function StatCard({ title, value, subtitle, trend, icon, gradient = 'from-blue-600/20 to-blue-500/10' }) {
  return (
    <Card hover className={`bg-gradient-to-br ${gradient} p-5`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="text-xs uppercase tracking-wide text-slate-400 mb-2">
            {title}
          </div>
          <div className="flex items-baseline gap-2">
            <div className="text-3xl font-bold text-slate-100">
              {value}
            </div>
            {subtitle && (
              <div className="text-sm text-slate-400">
                {subtitle}
              </div>
            )}
          </div>
          {trend && (
            <div className={`mt-2 text-xs font-medium ${trend.positive ? 'text-emerald-400' : 'text-rose-400'}`}>
              {trend.value}
            </div>
          )}
        </div>
        {icon && (
          <div className="text-3xl opacity-20">
            {icon}
          </div>
        )}
      </div>
    </Card>
  )
}

/* ===== EMPTY STATE ===== */
export function EmptyState({ icon, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
      {icon && (
        <div className="mb-4 text-5xl opacity-20">
          {icon}
        </div>
      )}
      <h3 className="text-lg font-semibold text-slate-300 mb-2">
        {title}
      </h3>
      {description && (
        <p className="text-sm text-slate-400 mb-6 max-w-md">
          {description}
        </p>
      )}
      {action}
    </div>
  )
}
