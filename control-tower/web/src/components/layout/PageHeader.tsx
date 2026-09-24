import type { ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useActiveProcess } from '../../lib/processConfig'

export function PageHeader({
  title,
  subtitle,
  actions,
  showProcessSwitcher = true,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
  showProcessSwitcher?: boolean
}) {
  const { active } = useActiveProcess()

  return (
    <div className="flex min-h-[72px] shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-6 lg:px-8">
      <div className="min-w-0">
        <div className="truncate text-[18px] font-bold">{title}</div>
        {subtitle && <div className="mt-0.5 text-[12.5px] text-text-secondary">{subtitle}</div>}
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        {showProcessSwitcher && (
          <Link
            to="/config"
            className="flex items-center gap-2 rounded-full border border-accent-border bg-accent-soft px-3.5 py-2 text-xs font-bold text-accent"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            <span className="hidden sm:inline">Active process: </span>
            {active?.title ?? '…'}
            <ChevronDown size={12} strokeWidth={2} />
          </Link>
        )}
        {actions}
      </div>
    </div>
  )
}
