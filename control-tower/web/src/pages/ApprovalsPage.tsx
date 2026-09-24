import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Code2 } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { useApprovalsList, useApprove } from '../lib/queries'
import { useAuth } from '../lib/auth'
import { relativeTime } from '../lib/utils'

const API_BASE = typeof window !== 'undefined' ? window.location.origin : ''

export function ApprovalsPage() {
  const { data: approvals, isLoading } = useApprovalsList()
  const approve = useApprove()
  const { user } = useAuth()
  const [showApi, setShowApi] = useState(false)

  return (
    <>
      <PageHeader
        title="Approval queue"
        subtitle="Cases paused above the risk threshold — approving resumes the agent from its LangGraph interrupt"
        actions={
          <Button variant="default" onClick={() => setShowApi((v) => !v)}>
            <Code2 size={14} strokeWidth={2} />
            API access
          </Button>
        }
      />

      <div className="flex flex-1 flex-col gap-3.5 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        {showApi && (
          <Card className="flex flex-col gap-3 px-5 py-[18px]">
            <div className="text-[13px] font-bold text-text-secondary">
              Integrate this queue into your own system
            </div>
            <p className="text-[12.5px] leading-relaxed text-text-secondary">
              <code className="font-mono text-accent">GET /approvals</code> returns every case currently paused for a
              human decision — poll it instead of scraping the dashboard. Generate a key for your integration from{' '}
              <Link to="/applications" className="font-semibold text-accent">
                Applications
              </Link>
              .
            </p>
            <pre className="overflow-x-auto rounded-lg border border-border-subtle bg-bg px-3.5 py-3 font-mono text-[11.5px] text-text-secondary">
{`curl ${API_BASE}/approvals

curl -X POST ${API_BASE}/approvals/<call_id> \\
  -H "Content-Type: application/json" \\
  -d '{"action": "approve", "actor": "you@company.com"}'`}
            </pre>
            <p className="text-[11.5px] text-text-muted">
              Bearer-key enforcement on these routes isn&apos;t wired up yet (see Applications) — right now they're
              open the same way the dashboard's own calls are.
            </p>
          </Card>
        )}

        {!isLoading && approvals?.length === 0 && (
          <Card className="px-6 py-10 text-center text-sm text-text-muted">
            Nothing waiting on a human right now.
          </Card>
        )}

        {approvals?.map((item) => {
          const acting = approve.isPending && approve.variables?.callId === item.call_id
          return (
            <Card key={item.call_id} className="flex flex-col gap-3.5 px-4 py-4 sm:px-[22px] sm:py-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                  <span className="font-mono text-[15px] font-bold">{item.case_id}</span>
                  <Badge tone="warning">{item.process}</Badge>
                  <span className="text-xs text-text-muted">requested {relativeTime(item.requested_at)}</span>
                </div>
                <Badge tone="warning">Awaiting decision</Badge>
              </div>

              <div className="grid grid-cols-2 gap-[18px] rounded-[10px] bg-surface-2 px-4 py-3.5 sm:grid-cols-4">
                <Field label="Why escalated" value={item.reason ?? '—'} />
                <Field label="Risk score" value={String(item.risk_score ?? '—')} mono color="var(--color-warning)" />
                <Field label="Confidence" value={item.confidence_score != null ? item.confidence_score.toFixed(2) : '—'} mono />
                <Field label="Tool call" value={item.tool_name ?? '—'} mono />
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <Link to={`/cases/${item.case_id}`} className="text-xs font-semibold text-accent">
                  View full trace →
                </Link>
                <div className="flex gap-2">
                  <Button
                    variant="danger-outline"
                    disabled={approve.isPending}
                    onClick={() =>
                      approve.mutate({ callId: item.call_id, action: 'reject', actor: user?.email ?? 'demo@aegis.dev' })
                    }
                  >
                    Reject
                  </Button>
                  <Button
                    variant="success-outline"
                    disabled={approve.isPending}
                    onClick={() =>
                      approve.mutate({ callId: item.call_id, action: 'approve', actor: user?.email ?? 'demo@aegis.dev' })
                    }
                  >
                    {acting ? 'Resuming…' : 'Approve & resume'}
                  </Button>
                </div>
              </div>
            </Card>
          )
        })}
      </div>
    </>
  )
}

function Field({ label, value, mono, color }: { label: string; value: string; mono?: boolean; color?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-semibold uppercase text-text-muted">{label}</div>
      <div className={mono ? 'mt-0.5 truncate font-mono text-sm font-bold' : 'mt-0.5 text-[12.5px] leading-snug'} style={{ color }}>
        {value}
      </div>
    </div>
  )
}
