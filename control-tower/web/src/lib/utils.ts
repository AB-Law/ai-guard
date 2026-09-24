import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}

export function riskColor(score: number | null | undefined): string {
  if (score == null) return 'var(--color-text-muted)'
  if (score >= 70) return 'var(--color-danger)'
  if (score >= 40) return 'var(--color-warning)'
  return 'var(--color-success)'
}

export function decisionBadgeTone(decision: string | null | undefined): 'success' | 'warning' | 'danger' | 'accent' | 'muted' {
  switch (decision) {
    case 'allow':
      return 'success'
    case 'escalate':
      return 'warning'
    case 'block':
      return 'danger'
    default:
      return 'muted'
  }
}

export function decisionLabel(decision: string | null | undefined, status: string | null | undefined): string {
  if (status === 'pending_approval') return 'Escalated'
  if (decision === 'allow') return 'Allowed'
  if (decision === 'block') return 'Blocked'
  if (decision === 'escalate') return 'Escalated'
  return 'Running'
}
