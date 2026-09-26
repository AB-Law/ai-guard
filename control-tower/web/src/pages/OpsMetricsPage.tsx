import { Activity } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { useOpsMetrics } from '../lib/queries'
import type { OpsMetricsSnapshot } from '../lib/types'

function fmt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  return String(n)
}

function fmtMs(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return 'Unavailable'
  return `${n.toFixed(1)} ms`
}

function fmtCost(n: number | null | undefined, isEstimate: boolean): string {
  if (n == null || Number.isNaN(n)) return 'Unavailable'
  const base = `$${n.toFixed(6)}`
  return isEstimate ? `${base} (estimate)` : base
}

function modelReasonLabel(reason: string | null): string {
  switch (reason) {
    case 'provider_usage_metadata_unavailable':
      return 'Provider did not expose token usage metadata on responses observed so far.'
    case 'pricing_not_configured':
      return 'Token counts available; set AEGIS_MODEL_PRICING_JSON to estimate cost.'
    case 'cost_unavailable':
      return 'Cost could not be estimated for the observed usage.'
    case 'metrics_snapshot_failed':
      return 'Metrics snapshot failed; values temporarily unavailable.'
    default:
      return 'Token and cost data unavailable.'
  }
}

export function OpsMetricsPage() {
  const { data, isLoading, isError, error } = useOpsMetrics()

  return (
    <>
      <PageHeader
        title="Operational metrics"
        subtitle="Request volume, guard decisions, latency, and observed model usage — never fabricated zeros"
        showProcessSwitcher={false}
      />

      <div className="flex flex-1 flex-col gap-[18px] overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        {isLoading && (
          <Card className="px-5 py-8 text-center text-sm text-text-muted">Loading metrics…</Card>
        )}
        {isError && (
          <Card className="border-danger/40 bg-danger-soft px-5 py-4 text-sm font-semibold text-danger">
            Could not load ops metrics
            {error instanceof Error ? ` — ${error.message}` : ''}.
          </Card>
        )}
        {data && <MetricsBody data={data} />}
        {!isLoading && !isError && !data && (
          <Card className="px-5 py-8 text-center text-sm text-text-muted">
            No metrics yet — traffic will appear here after API requests.
          </Card>
        )}
      </div>
    </>
  )
}

function MetricsBody({ data }: { data: OpsMetricsSnapshot }) {
  const decisions = data.guards.decisions
  const decisionTotal = decisions.allow + decisions.block + decisions.escalate
  const emptyTraffic = data.requests.total === 0 && decisionTotal === 0

  return (
    <>
      {emptyTraffic && (
        <Card className="flex items-center gap-3 px-5 py-4 text-sm text-text-secondary">
          <Activity size={18} strokeWidth={1.6} className="shrink-0 text-text-muted" />
          Empty — no requests or guard evaluations recorded in this process yet.
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Kpi label="Requests" value={fmt(data.requests.total)} />
        <Kpi
          label="Guard evaluations"
          value={fmt(data.guards.evaluations)}
          footer={`${data.guards.errors} error(s)`}
        />
        <Kpi label="Avg guard latency" value={fmtMs(data.guards.avg_latency_ms)} />
        <Kpi
          label="Approvals"
          value={fmt(data.approvals.approved + data.approvals.denied)}
          footer={`${data.approvals.approved} approved · ${data.approvals.denied} denied`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="flex flex-col overflow-hidden">
          <div className="border-b border-border px-[18px] py-4 text-sm font-bold">Decision mix</div>
          <div className="flex flex-col gap-3 px-[18px] py-4 text-sm">
            {decisionTotal === 0 ? (
              <p className="text-text-muted">No guard decisions yet.</p>
            ) : (
              <>
                <BarRow label="Allow" count={decisions.allow} total={decisionTotal} tone="success" />
                <BarRow label="Escalate" count={decisions.escalate} total={decisionTotal} tone="warning" />
                <BarRow label="Block" count={decisions.block} total={decisionTotal} tone="danger" />
              </>
            )}
          </div>
        </Card>

        <Card className="flex flex-col overflow-hidden">
          <div className="border-b border-border px-[18px] py-4 text-sm font-bold">Request outcomes</div>
          <div className="flex flex-col gap-2 px-[18px] py-4 text-sm">
            {Object.keys(data.requests.by_outcome).length === 0 ? (
              <p className="text-text-muted">No HTTP outcomes yet.</p>
            ) : (
              Object.entries(data.requests.by_outcome).map(([outcome, count]) => (
                <div key={outcome} className="flex justify-between text-text-secondary">
                  <span className="font-medium capitalize">{outcome.replace('_', ' ')}</span>
                  <span className="tabular-nums text-text-primary">{count}</span>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      <Card className="flex flex-col overflow-hidden">
        <div className="border-b border-border px-[18px] py-4 text-sm font-bold">Latency by route</div>
        {data.requests.by_route.length === 0 ? (
          <p className="px-[18px] py-4 text-sm text-text-muted">No route samples yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-sm">
              <thead className="border-b border-border text-[11px] uppercase tracking-wide text-text-muted">
                <tr>
                  <th className="px-[18px] py-2.5 font-semibold">Route</th>
                  <th className="px-[18px] py-2.5 font-semibold">Count</th>
                  <th className="px-[18px] py-2.5 font-semibold">Avg duration</th>
                </tr>
              </thead>
              <tbody>
                {data.requests.by_route.map((row) => (
                  <tr key={row.route} className="border-b border-border/60 last:border-0">
                    <td className="px-[18px] py-2.5 font-mono text-[12.5px]">{row.route}</td>
                    <td className="px-[18px] py-2.5 tabular-nums">{row.count}</td>
                    <td className="px-[18px] py-2.5 tabular-nums text-text-secondary">
                      {row.avg_duration_ms == null ? 'Unavailable' : `${row.avg_duration_ms.toFixed(1)} ms`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="flex flex-col overflow-hidden">
        <div className="border-b border-border px-[18px] py-4 text-sm font-bold">Model tokens & cost</div>
        <div className="flex flex-col gap-3 px-[18px] py-4 text-sm">
          {!data.model.usage_available ? (
            <p className="text-text-muted">{modelReasonLabel(data.model.unavailable_reason)}</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <MiniStat label="Prompt tokens" value={fmt(data.model.prompt_tokens)} />
                <MiniStat label="Completion tokens" value={fmt(data.model.completion_tokens)} />
                <MiniStat
                  label="Estimated cost"
                  value={fmtCost(data.model.estimated_cost_usd, data.model.estimated_cost_is_estimate)}
                />
              </div>
              {data.model.estimated_cost_usd == null && (
                <p className="text-[12.5px] text-text-muted">
                  {modelReasonLabel(data.model.unavailable_reason)}
                </p>
              )}
              <p className="text-[11.5px] text-text-muted">
                {data.model.calls_with_usage} call(s) with usage · {data.model.calls_without_usage} without
                · cost is always an estimate when pricing is configured
              </p>
            </>
          )}
        </div>
      </Card>
    </>
  )
}

function Kpi({
  label,
  value,
  footer,
}: {
  label: string
  value: string
  footer?: string
}) {
  return (
    <Card className="flex flex-col gap-1 px-[18px] py-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">{label}</div>
      <div className="text-[22px] font-bold tabular-nums tracking-tight">{value}</div>
      {footer && <div className="text-[11.5px] text-text-muted">{footer}</div>}
    </Card>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-2 px-3 py-2.5">
      <div className="text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">{label}</div>
      <div className="mt-0.5 text-sm font-bold tabular-nums">{value}</div>
    </div>
  )
}

function BarRow({
  label,
  count,
  total,
  tone,
}: {
  label: string
  count: number
  total: number
  tone: 'success' | 'warning' | 'danger'
}) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0
  const color =
    tone === 'success' ? 'bg-success' : tone === 'warning' ? 'bg-warning' : 'bg-danger'
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-[12.5px]">
        <span className="font-medium text-text-secondary">{label}</span>
        <span className="tabular-nums text-text-primary">
          {count} · {pct}%
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
