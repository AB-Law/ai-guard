import { NavLink } from 'react-router-dom'
import {
  LayoutGrid,
  Plug,
  CircleCheck,
  ScrollText,
  Link2,
  SlidersHorizontal,
  ShieldCheck,
  LogOut,
  Code2,
  Activity,
} from 'lucide-react'
import { cn } from '../../lib/utils'
import { Badge } from '../ui/Badge'
import { useAuth } from '../../lib/auth'

const navItems = [
  { to: '/', label: 'Overview', icon: LayoutGrid, end: true },
  { to: '/applications', label: 'Applications', icon: Plug },
  { to: '/approvals', label: 'Approvals', icon: CircleCheck, badgeKey: 'approvals' as const },
  { to: '/logs', label: 'Logs', icon: ScrollText },
  { to: '/audit', label: 'Audit & Integrity', icon: Link2 },
  { to: '/metrics', label: 'Ops metrics', icon: Activity },
  { to: '/config', label: 'Config', icon: SlidersHorizontal },
  { to: '/developers', label: 'Developers', icon: Code2 },
]

// Below `lg` this collapses to an icon-only rail (no hamburger/overlay state
// needed) so the layout never has to overlap content to fit a full sidebar.
export function Sidebar({ pendingApprovals = 0 }: { pendingApprovals?: number }) {
  const { user, logout } = useAuth()
  return (
    <div className="flex w-[64px] shrink-0 flex-col gap-6 border-r border-border bg-[#0d1117] p-2.5 lg:w-[230px] lg:p-3.5">
      <div className="flex items-center justify-center gap-2.5 px-0 lg:justify-start lg:px-1.5">
        <ShieldCheck size={22} className="shrink-0 text-accent" strokeWidth={1.6} />
        <div className="hidden flex-col leading-tight lg:flex">
          <span className="text-[15px] font-extrabold tracking-wide">AEGIS</span>
          <span className="text-[9.5px] font-semibold uppercase tracking-wider text-text-muted">
            Control Tower
          </span>
        </div>
      </div>

      <nav className="flex flex-col gap-0.5">
        {navItems.map(({ to, label, icon: Icon, end, badgeKey }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={label}
            className={({ isActive }) =>
              cn(
                'relative flex items-center justify-center gap-2.5 rounded-lg px-2.5 py-2.5 text-[13.5px] font-medium text-text-secondary transition-colors lg:justify-start lg:px-3 lg:py-2',
                isActive ? 'bg-accent-soft text-accent' : 'hover:bg-surface-hover hover:text-text-primary',
              )
            }
          >
            <Icon size={17} strokeWidth={1.6} className="shrink-0" />
            <span className="hidden truncate lg:inline">{label}</span>
            {badgeKey === 'approvals' && pendingApprovals > 0 && (
              <>
                <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-warning lg:hidden" />
                <Badge tone="warning" dot={false} className="ml-auto hidden px-1.5 py-0.5 lg:inline-flex">
                  {pendingApprovals}
                </Badge>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto flex flex-col gap-2.5">
        <button
          onClick={logout}
          title={user ? `Sign out (${user.email})` : 'Sign out'}
          className="flex items-center justify-center gap-2.5 rounded-lg px-2.5 py-2.5 text-[13.5px] font-medium text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary lg:justify-start lg:px-3 lg:py-2"
        >
          <LogOut size={17} strokeWidth={1.6} className="shrink-0" />
          <span className="hidden truncate lg:inline">{user?.email ?? 'Sign out'}</span>
        </button>
        <div className="hidden rounded-lg border border-border bg-surface p-2.5 text-[10.5px] text-text-muted lg:block">
          <div className="flex items-center gap-1.5 text-[10.5px] font-bold tracking-wide text-success">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            DEMO · OFFLINE MODE
          </div>
          <div className="mt-1 leading-snug">No live API key required for this run</div>
        </div>
      </div>
    </div>
  )
}
