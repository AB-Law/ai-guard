import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, TriangleAlert } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { useCase, useCaseAudit } from '../lib/queries'
import { cn, decisionBadgeTone, decisionLabel } from '../lib/utils'
import type { AuditEventType, AuditLogEntry, GatewayDecision } from '../lib/types'

const PIPELINE: { key: AuditEventType | 'action'; label: string }[] = [
  { key: 'retrieval', label: 'Retrieve' },
  { key: 'injection_flag', label: 'Scan' },
  { key: 'policy_check', label: 'Gateway' },
  { key: 'action', label: 'Action' },
  { key: 'approval', label: 'Approval' },
]

type ScoreKey = 'risk' | 'confidence' | 'evidence'

export function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const { data: kase, isLoading } = useCase(caseId)
  const { data: audit } = useCaseAudit(caseId)
  const [selected, setSelected] = useState<ScoreKey>('risk')

  const entries = audit?.entries ?? []
  const injectionEntry = entries.find((e) => e.event_type === 'injection_flag')
  const policyEntry = entries.find((e) => e.event_type === 'policy_check')
  const claimEntry = entries.find((e) => e.event_type === 'output_claim')
  const retrievalEntry = entries.find((e) => e.event_type === 'retrieval')
  const toolCallEntry = entries.find((e) => e.event_type === 'tool_call')

  const gw = kase?.gateway_decision

  const panel = useMemo(() => buildPanel(selected, { gw, policyEntry, claimEntry, process: kase?.process }), [
    selected,
    gw,
    policyEntry,
    claimEntry,
    kase?.process,
  ])

  if (isLoading || !kase) {
    return (
      <>
        <PageHeader title="Case" subtitle="Loading…" showProcessSwitcher={false} />
        <div className="flex-1 px-8 py-6 text-sm text-text-muted">Fetching case…</div>
      </>
    )
  }

  return (
    <>
      <div className="flex min-h-[72px] shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <Link to="/" className="flex items-center gap-1.5 text-[13px] font-semibold text-text-secondary hover:text-text-primary">
            <ArrowLeft size={14} strokeWidth={2} />
            Live traffic
          </Link>
          <span className="hidden text-border sm:inline">/</span>
          <span className="font-mono text-[15px] font-bold">{kase.case_id}</span>
          <Badge tone={decisionBadgeTone(gw?.decision)}>{decisionLabel(gw?.decision, kase.status)}</Badge>
        </div>
        <div className="flex items-center gap-2.5 text-xs text-text-secondary">
          <Badge tone="accent">{kase.process}</Badge>
          {kase.origin === 'policy_change' && <Badge tone="warning">Policy change</Badge>}
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-[22px] overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        {kase.origin === 'policy_change' && (
          <Card className="flex flex-col gap-2 px-[22px] py-[18px]">
            <div className="text-[13px] font-bold text-text-secondary">Proposed learned rule</div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="Rule text" value={String(kase.request?.rule_text ?? '—')} mono />
              <Field label="Incident" value={String(kase.request?.source_incident_id ?? '—')} mono />
              <Field
                label="Span preview"
                value={String(kase.request?.matched_span_preview ?? '—')}
              />
            </div>
            {typeof kase.request?.matched_span_hash === 'string' && (
              <div className="font-mono text-[11px] text-text-muted">
                {kase.request.matched_span_hash}
              </div>
            )}
          </Card>
        )}
        <Card className="grid grid-cols-2 gap-[18px] px-[22px] py-[18px] sm:grid-cols-3 lg:grid-cols-5">
          <Field label="Source app" value={kase.source_app ?? '—'} />
          <Field label="Process" value={kase.process} mono />
          <Field
            label="Tool call"
            value={
              String(
                (entries.find((e) => e.event_type === 'tool_call')?.payload as { tool_name?: string } | undefined)
                  ?.tool_name ??
                  (kase.request as { tool_name?: string } | null)?.tool_name ??
                  '—',
              )
            }
            mono
          />
          <Field label="Gateway decision" value={gw ? gw.decision : 'pending'} mono />
          <Field label="Call ID" value={kase.call_id || '—'} mono muted />
        </Card>

        <Card className="px-[22px] py-5">
          <div className="mb-4 text-[13px] font-bold text-text-secondary">Pipeline</div>
          <div className="flex items-start">
            {PIPELINE.map((stage) => {
              const reached =
                stage.key === 'action'
                  ? !!kase.tool_result || gw?.decision === 'block'
                  : stage.key === 'approval'
                    ? kase.status === 'pending_approval' || kase.status === 'completed'
                    : entries.some((e) => e.event_type === stage.key)
              return (
                <div key={stage.key} className="flex w-1/5 flex-col items-center gap-2">
                  <div
                    className={cn(
                      'flex h-[34px] w-[34px] items-center justify-center rounded-full border-[1.5px] text-xs font-bold',
                      reached ? 'border-accent bg-accent-soft text-accent' : 'border-border text-text-muted',
                    )}
                  >
                    {reached ? '✓' : ''}
                  </div>
                  <div className="text-center text-[12.5px] font-bold">{stage.label}</div>
                </div>
              )
            })}
          </div>
        </Card>

        {injectionEntry && (
          <Card className="flex items-start gap-3 border-warning/40 bg-warning-soft px-[18px] py-3.5">
            <TriangleAlert size={18} strokeWidth={1.6} className="mt-0.5 shrink-0 text-warning" />
            <div>
              <div className="text-[13px] font-bold text-warning">Prompt injection detected</div>
              <div className="mt-0.5 text-[12.5px] leading-relaxed text-text-secondary">
                {String((injectionEntry.payload as { snippet?: string }).snippet ?? 'Untrusted content flagged at retrieval.')} Content
                was tagged untrusted; the gateway still evaluated the resulting action against policy regardless of what
                the agent was told.
              </div>
            </div>
          </Card>
        )}

        <EvidenceCard
          retrievalEntry={retrievalEntry}
          policyEntry={policyEntry}
          claimEntry={claimEntry}
          toolCallEntry={toolCallEntry}
          gw={gw}
          toolResult={kase.tool_result}
        />

        <div>
          <div className="mb-2.5 text-[13px] font-bold text-text-secondary">Scores — click to see the evidence behind each one</div>
          <div className="grid grid-cols-1 items-stretch gap-3.5 sm:grid-cols-2 xl:grid-cols-[2fr_2fr_2fr_3fr]">
            <ScoreCard
              label="Risk score"
              value={gw ? String(gw.risk_score) : '—'}
              suffix="/100"
              color={riskTone(gw?.risk_score)}
              selected={selected === 'risk'}
              onClick={() => setSelected('risk')}
            />
            <ScoreCard
              label="Confidence"
              value={gw ? gw.confidence_score.toFixed(2) : '—'}
              selected={selected === 'confidence'}
              onClick={() => setSelected('confidence')}
            />
            <ScoreCard
              label="Evidence (groundedness)"
              value={gw ? gw.evidence_score.toFixed(2) : '—'}
              color={gw && gw.evidence_score < 0.5 ? 'var(--color-danger)' : undefined}
              selected={selected === 'evidence'}
              onClick={() => setSelected('evidence')}
            />
            <Card className="flex flex-col gap-2 bg-surface-2 px-[18px] py-4">
              <div className="text-[12.5px] font-bold">{panel.title}</div>
              <div className="text-[12.5px] leading-relaxed text-text-secondary">{panel.body}</div>
              <div className="mt-0.5 border-t border-border pt-2 font-mono text-[11px] text-text-muted">{panel.source}</div>
            </Card>
          </div>
        </div>

        {gw && (
          <Card className="flex flex-col gap-2.5 px-[22px] py-[18px]">
            <div className="text-[13px] font-bold text-text-secondary">Gateway decision</div>
            <div className="flex items-center gap-2.5">
              <Badge tone={decisionBadgeTone(gw.decision)}>{gw.decision}</Badge>
              <span className="text-[12.5px] text-text-secondary">{gw.reason}</span>
            </div>
            {gw.policy_refs.length > 0 && (
              <div className="mt-1 rounded-lg border border-border-subtle bg-bg px-3 py-2.5 font-mono text-xs text-text-muted">
                policy_refs: [{gw.policy_refs.join(', ')}]
              </div>
            )}
          </Card>
        )}

        <Link to="/audit" className="text-[12.5px] font-semibold text-accent">
          View full audit trail →
        </Link>
      </div>
    </>
  )
}

function EvidenceCard({
  retrievalEntry,
  policyEntry,
  claimEntry,
  toolCallEntry,
  gw,
  toolResult,
}: {
  retrievalEntry: AuditLogEntry | undefined
  policyEntry: AuditLogEntry | undefined
  claimEntry: AuditLogEntry | undefined
  toolCallEntry: AuditLogEntry | undefined
  gw: GatewayDecision | null | undefined
  toolResult: Record<string, unknown> | null
}) {
  if (!retrievalEntry && !policyEntry && !toolCallEntry) return null

  const chunks =
    (retrievalEntry?.payload as { chunks?: { id: string; source: string; excerpt: string }[] } | undefined)
      ?.chunks ?? []
  const topChunk = chunks[0]

  const policyPayload = policyEntry?.payload as
    | { unsupported_claims?: string[]; entailment?: { violated_clauses?: string[] } }
    | undefined
  const claimText =
    (claimEntry?.payload as { claim?: string } | undefined)?.claim ?? policyPayload?.unsupported_claims?.[0]
  const clauses = [...(gw?.policy_refs ?? []), ...(policyPayload?.entailment?.violated_clauses ?? [])]

  const toolPayload = toolCallEntry?.payload as { tool_name?: string; tool_args?: Record<string, unknown> } | undefined
  const proposed = toolPayload
    ? `${toolPayload.tool_name ?? '—'}(${JSON.stringify(toolPayload.tool_args ?? {})})`
    : '—'
  const actual = toolResult ? JSON.stringify(toolResult) : gw?.decision === 'block' ? 'Blocked — not executed' : '—'

  return (
    <Card className="flex flex-col gap-3 px-[22px] py-[18px]">
      <div className="text-[13px] font-bold text-text-secondary">Evidence</div>
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
        <EvidenceField label="Retrieved document">
          {topChunk ? `${topChunk.source} (${topChunk.id})` : 'No documents retrieved for this case.'}
        </EvidenceField>
        <EvidenceField label="Relevant quoted passage" mono>
          {claimText ?? topChunk?.excerpt ?? 'No passage recorded.'}
        </EvidenceField>
        <EvidenceField label="Policy clause">
          {clauses.length > 0 ? clauses.join(', ') : 'No policy clause cited.'}
        </EvidenceField>
        <EvidenceField label="Action proposed vs. taken" mono>
          <span className="block truncate" title={proposed}>
            Proposed: {proposed}
          </span>
          <span className="mt-0.5 block truncate" title={actual}>
            Actual: {actual}
          </span>
        </EvidenceField>
      </div>
    </Card>
  )
}

function EvidenceField({ label, mono, children }: { label: string; mono?: boolean; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg px-3 py-2.5">
      <div className="text-[11px] font-semibold uppercase text-text-muted">{label}</div>
      <div className={cn('mt-1 line-clamp-3 text-[12.5px] leading-relaxed text-text-secondary', mono && 'font-mono text-[11.5px]')}>
        {children}
      </div>
    </div>
  )
}

function riskTone(score: number | undefined): string | undefined {
  if (score == null) return undefined
  if (score >= 70) return 'var(--color-danger)'
  if (score >= 40) return 'var(--color-warning)'
  return 'var(--color-success)'
}

function buildPanel(
  key: ScoreKey,
  ctx: {
    gw: GatewayDecision | null | undefined
    policyEntry: AuditLogEntry | undefined
    claimEntry: AuditLogEntry | undefined
    process: string | undefined
  },
) {
  const { gw, policyEntry, claimEntry, process } = ctx
  if (key === 'risk') {
    return {
      title: gw ? `Risk score — ${gw.risk_score} / 100` : 'Risk score',
      body: gw?.reason ?? 'No gateway decision recorded yet for this case.',
      source: policyEntry
        ? `${process ?? 'process'} · policy_check @ ${new Date(policyEntry.timestamp).toLocaleTimeString()}`
        : `configs/${process ?? 'process'}.yaml · approval_threshold`,
    }
  }
  if (key === 'confidence') {
    return {
      title: gw ? `Confidence — ${gw.confidence_score.toFixed(2)}` : 'Confidence',
      body: 'How closely the agent’s tool-call reasoning matched the retrieved policy language and how complete the retrieved evidence set was.',
      source: 'guardrails/risk_scorer.py · confidence aggregation',
    }
  }
  return {
    title: gw ? `Evidence (groundedness) — ${gw.evidence_score.toFixed(2)}` : 'Evidence',
    body: claimEntry
      ? String((claimEntry.payload as { claim?: string }).claim ?? 'An agent claim could not be matched to any retrieved document.')
      : 'Every claim the agent made was matched to a retrieved passage — no unsupported output flagged.',
    source: claimEntry ? 'output_verifier · groundedness check' : 'output_verifier · no unsupported claims',
  }
}

function ScoreCard({
  label,
  value,
  suffix,
  color,
  selected,
  onClick,
}: {
  label: string
  value: string
  suffix?: string
  color?: string
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex flex-col gap-1.5 rounded-xl border px-[18px] py-4 text-left transition-colors',
        selected ? 'border-accent bg-accent-soft' : 'border-border bg-surface hover:bg-surface-hover',
      )}
    >
      <span className="text-[11.5px] font-semibold uppercase text-text-muted">{label}</span>
      <span className="font-mono text-[28px] font-semibold" style={{ color }}>
        {value}
        {suffix && <span className="text-sm text-text-muted">{suffix}</span>}
      </span>
      <span className="text-[11.5px] font-semibold text-accent">View evidence →</span>
    </button>
  )
}

function Field({ label, value, mono, muted }: { label: string; value: string; mono?: boolean; muted?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-semibold uppercase text-text-muted">{label}</div>
      <div
        title={value}
        className={cn(
          'mt-0.5 truncate text-[13.5px] font-semibold',
          mono && 'font-mono',
          muted && 'text-text-secondary',
        )}
      >
        {value}
      </div>
    </div>
  )
}
