import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { StageDots } from '../components/StageDots'
import { useTrafficRecent } from '../lib/queries'
import { useSeedDemo } from '../lib/queries'
import { cn, decisionBadgeTone, decisionLabel, relativeTime, riskColor } from '../lib/utils'

const FILTERS = ['all', 'allow', 'escalate', 'block'] as const
type Filter = (typeof FILTERS)[number]
const FILTER_LABELS: Record<Filter, string> = { all: 'All', allow: 'Allowed', escalate: 'Escalated', block: 'Blocked' }

export function OverviewPage() {
  const [filter, setFilter] = useState<Filter>('all')
  const { data, isLoading } = useTrafficRecent({ limit: 50 })
  const seedDemo = useSeedDemo()

  const rows = (data?.cases ?? []).filter((r) => filter === 'all' || r.decision === filter)

  const total = data?.total_cases ?? 0
  const escalated = (data?.cases ?? []).filter((r) => r.status === 'pending_approval').length
  const blocked = (data?.cases ?? []).filter((r) => r.decision === 'block').length
  const scored = (data?.cases ?? []).filter((r) => r.risk_score != null)
  const avgRisk = scored.length
    ? Math.round(scored.reduce((sum, r) => sum + (r.risk_score ?? 0), 0) / scored.length)
    : 0

  return (
    <>
      <PageHeader
        title="Live Traffic"
        subtitle="Every case moving through Retrieve → Scan → Gateway → Action → Approval"
        actions={
          <Button variant="default" onClick={() => seedDemo.mutate()} disabled={seedDemo.isPending}>
            {seedDemo.isPending ? 'Loading demo pack…' : 'Load demo pack'}
          </Button>
        }
      />

      <div className="flex flex-1 flex-col gap-[22px] overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
          <Kpi label="Total cases" value={String(total)} />
          <Kpi
            label="Escalation queue"
            value={String(escalated)}
            valueColor="var(--color-warning)"
            footer={
              <Link to="/approvals" className="text-xs font-semibold text-warning">
                view approvals →
              </Link>
            }
          />
          <Kpi label="Blocked" value={String(blocked)} valueColor="var(--color-danger)" footer="unauthorized tool use" />
          <Kpi label="Avg risk score" value={String(avgRisk)}>
            <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full bg-accent" style={{ width: `${Math.min(avgRisk, 100)}%` }} />
            </div>
          </Kpi>
        </div>

        <Card className="flex flex-1 flex-col overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-[18px] py-4">
            <span className="text-sm font-bold">Recent cases</span>
            <div className="flex flex-wrap gap-2">
              {FILTERS.map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={cn(
                    'rounded-full border border-border px-3 py-1.5 text-xs font-semibold text-text-secondary',
                    filter === f && 'border-text-muted bg-surface-2 text-text-primary',
                  )}
                >
                  {FILTER_LABELS[f]}
                </button>
              ))}
            </div>
          </div>

          <div className="overflow-auto">
            <table className="w-full min-w-[760px] border-collapse">
              <thead>
                <tr className="text-left text-[10.5px] font-bold uppercase tracking-wide text-text-muted">
                  <th className="w-[120px] border-b border-border px-4 py-2.5">Case</th>
                  <th className="w-[150px] border-b border-border px-4 py-2.5">Process</th>
                  <th className="border-b border-border px-4 py-2.5">Pipeline stage</th>
                  <th className="w-[70px] border-b border-border px-4 py-2.5">Risk</th>
                  <th className="w-[110px] border-b border-border px-4 py-2.5">Decision</th>
                  <th className="w-[90px] border-b border-border px-4 py-2.5">Time</th>
                </tr>
              </thead>
              <tbody>
                {!isLoading && rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-sm text-text-muted">
                      No traffic yet — load the demo pack or run{' '}
                      <code className="font-mono text-text-secondary">scripts/traffic_sim.py</code>.
                    </td>
                  </tr>
                )}
                {rows.map((row) => (
                  <tr key={row.case_id} className="border-b border-border-subtle text-[13px] last:border-none hover:bg-surface-hover">
                    <td className="px-4 py-3.5">
                      <Link to={`/cases/${row.case_id}`} className="font-mono font-semibold text-accent">
                        {row.case_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3.5 text-text-secondary">{row.process}</td>
                    <td className="px-4 py-3.5">
                      <StageDots stages={row.stages} decision={row.decision} status={row.status} />
                    </td>
                    <td className="px-4 py-3.5 font-mono font-semibold" style={{ color: riskColor(row.risk_score) }}>
                      {row.risk_score ?? '—'}
                    </td>
                    <td className="px-4 py-3.5">
                      <Badge tone={decisionBadgeTone(row.decision)}>{decisionLabel(row.decision, row.status)}</Badge>
                    </td>
                    <td className="px-4 py-3.5 text-xs text-text-muted">{relativeTime(row.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  )
}

function Kpi({
  label,
  value,
  valueColor,
  footer,
  children,
}: {
  label: string
  value: string
  valueColor?: string
  footer?: React.ReactNode
  children?: React.ReactNode
}) {
  return (
    <Card className="flex flex-col gap-1.5 px-5 py-[18px]">
      <span className="text-[11.5px] font-semibold uppercase tracking-wide text-text-muted">{label}</span>
      <span className="font-mono text-[30px] font-semibold" style={{ color: valueColor }}>
        {value}
      </span>
      {typeof footer === 'string' ? <span className="text-xs text-text-secondary">{footer}</span> : footer}
      {children}
    </Card>
  )
}
