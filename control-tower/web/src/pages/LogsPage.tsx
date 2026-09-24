import { useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Search } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { useAuditEntries } from '../lib/queries'
import { cn } from '../lib/utils'
import type { AuditLogEntry } from '../lib/types'

const EVENT_TAG_COLOR: Record<string, string> = {
  retrieval: 'var(--color-accent)',
  tool_call: 'var(--color-accent)',
  policy_check: 'var(--color-success)',
  injection_flag: 'var(--color-danger)',
  approval: 'var(--color-warning)',
  output_claim: 'var(--color-accent)',
}

const FIELDS = ['process', 'event_type', 'case', 'decision'] as const
type Field = (typeof FIELDS)[number]

interface Token {
  field: Field | null
  value: string
  raw: string
}

function parseQuery(query: string): Token[] {
  return query
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((raw) => {
      const idx = raw.indexOf(':')
      if (idx > 0) {
        const field = raw.slice(0, idx).toLowerCase()
        if ((FIELDS as readonly string[]).includes(field)) {
          return { field: field as Field, value: raw.slice(idx + 1).toLowerCase(), raw }
        }
      }
      return { field: null, value: raw.toLowerCase(), raw }
    })
}

function caseIdOf(entry: AuditLogEntry): string {
  return String((entry.payload as { case_id?: string }).case_id ?? '')
}

function fieldValue(entry: AuditLogEntry, field: Field): string {
  switch (field) {
    case 'process':
      return entry.process
    case 'event_type':
      return entry.event_type
    case 'case':
      return caseIdOf(entry)
    case 'decision':
      return entry.scores?.decision ?? ''
  }
}

function matchesToken(entry: AuditLogEntry, token: Token): boolean {
  if (token.field) {
    return fieldValue(entry, token.field).toLowerCase().includes(token.value)
  }
  const haystack = `${entry.event_type} ${entry.process} ${entry.step_id} ${caseIdOf(entry)} ${JSON.stringify(entry.payload)}`.toLowerCase()
  return haystack.includes(token.value)
}

function matchesTokens(entry: AuditLogEntry, tokens: Token[]): boolean {
  return tokens.every((t) => matchesToken(entry, t))
}

// Toggle a `field:value` token in the query string — clicking the same facet
// again clears it; clicking a different value for the same field replaces it
// (one active value per field, like a normal faceted-search sidebar).
function toggleToken(query: string, field: Field, value: string): string {
  const target = `${field}:${value}`
  const tokens = query.trim().split(/\s+/).filter(Boolean)
  const alreadyActive = tokens.some((t) => t.toLowerCase() === target.toLowerCase())
  const withoutField = tokens.filter((t) => !t.toLowerCase().startsWith(`${field}:`))
  const next = alreadyActive ? withoutField : [...withoutField, target]
  return next.join(' ')
}

export function LogsPage() {
  const [query, setQuery] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [live, setLive] = useState(true)
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [highlighted, setHighlighted] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const { data: entriesResponse, isLoading } = useAuditEntries({ limit: 200 }, { live })
  const entries = useMemo(() => entriesResponse?.entries ?? [], [entriesResponse])

  const tokens = useMemo(() => parseQuery(query), [query])
  const rows = useMemo(() => entries.filter((e) => matchesTokens(e, tokens)), [entries, tokens])

  // Each facet's own counts ignore its own active filter (so you can still see
  // — and click — the other values), but respect every other active filter.
  function facetCounts(field: Field): Record<string, number> {
    const scoped = entries.filter((e) => matchesTokens(e, tokens.filter((t) => t.field !== field)))
    const out: Record<string, number> = {}
    for (const e of scoped) {
      const v = fieldValue(e, field)
      if (!v) continue
      out[v] = (out[v] ?? 0) + 1
    }
    return out
  }
  const byProcess = useMemo(() => facetCounts('process'), [entries, tokens])
  const byEvent = useMemo(() => facetCounts('event_type'), [entries, tokens])
  const byDecision = useMemo(() => facetCounts('decision'), [entries, tokens])

  const activeValue = (field: Field): string | null => tokens.find((t) => t.field === field)?.value ?? null

  const bars = useMemo(() => buildHistogram(rows), [rows])

  // Autocomplete: suggest field prefixes for a fresh token, or known values
  // once a field: prefix has been typed.
  const suggestions = useMemo(() => {
    const partial = query.slice(0, inputRef.current?.selectionStart ?? query.length)
    const currentToken = partial.split(/\s+/).pop() ?? ''
    if (!currentToken) return []
    const colonIdx = currentToken.indexOf(':')
    if (colonIdx < 0) {
      return FIELDS.filter((f) => f.startsWith(currentToken.toLowerCase())).map((f) => `${f}:`)
    }
    const field = currentToken.slice(0, colonIdx).toLowerCase()
    const valuePrefix = currentToken.slice(colonIdx + 1).toLowerCase()
    if (!(FIELDS as readonly string[]).includes(field)) return []
    const distinct = new Set<string>()
    for (const e of entries) {
      const v = fieldValue(e, field as Field)
      if (v && v.toLowerCase().startsWith(valuePrefix)) distinct.add(v)
    }
    return Array.from(distinct)
      .slice(0, 8)
      .map((v) => `${field}:${v}`)
  }, [query, entries])

  function applySuggestion(suggestion: string) {
    const parts = query.trim().split(/\s+/).filter(Boolean)
    parts.pop()
    const next = [...parts, suggestion].join(' ') + (suggestion.endsWith(':') ? '' : ' ')
    setQuery(next)
    setHighlighted(0)
    inputRef.current?.focus()
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (!showSuggestions || suggestions.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlighted((h) => (h + 1) % suggestions.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlighted((h) => (h - 1 + suggestions.length) % suggestions.length)
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      applySuggestion(suggestions[highlighted])
    } else if (e.key === 'Escape') {
      setShowSuggestions(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Logs"
        subtitle="Search every retrieval, decision, tool call and score across all processes"
        showProcessSwitcher={false}
        actions={
          <button
            onClick={() => setLive((v) => !v)}
            className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3.5 py-2 text-[12.5px] font-bold"
            style={{ color: live ? 'var(--color-success)' : 'var(--color-text-muted)' }}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {live ? 'Live tail' : 'Paused'}
          </button>
        }
      />

      <div className="flex flex-1 flex-col overflow-hidden px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        <div className="relative mb-3.5">
          <Card className="flex flex-1 items-center gap-2 px-3.5 py-2.5">
            <Search size={15} strokeWidth={1.7} className="shrink-0 text-text-secondary" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setHighlighted(0)
                setShowSuggestions(true)
              }}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 120)}
              onKeyDown={handleKeyDown}
              placeholder="process:onboarding_kyc event_type:injection_flag …"
              className="w-full bg-transparent font-mono text-[13px] text-text-primary placeholder:text-text-muted outline-none"
            />
          </Card>
          {showSuggestions && suggestions.length > 0 && (
            <Card className="absolute left-0 right-0 top-[calc(100%+4px)] z-10 flex flex-col overflow-hidden py-1">
              {suggestions.map((s, i) => (
                <button
                  key={s}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => applySuggestion(s)}
                  className={cn(
                    'px-3.5 py-2 text-left font-mono text-[12.5px]',
                    i === highlighted ? 'bg-accent-soft text-accent' : 'text-text-secondary hover:bg-surface-hover',
                  )}
                >
                  {s}
                </button>
              ))}
            </Card>
          )}
        </div>

        <Card className="mb-3.5 flex h-16 items-end gap-[3px] px-4 py-3">
          {bars.map((b, i) => (
            <div key={i} className="flex h-full flex-1 flex-col-reverse gap-px">
              <div className="rounded-[1px] bg-success" style={{ height: `${b.g}%` }} />
              <div className="rounded-[1px] bg-warning" style={{ height: `${b.a}%` }} />
              <div className="rounded-[1px] bg-danger" style={{ height: `${b.r}%` }} />
            </div>
          ))}
        </Card>

        <div className="flex flex-1 flex-col gap-4 overflow-hidden lg:flex-row lg:gap-0">
          <div className="flex shrink-0 gap-5 overflow-x-auto pb-1 lg:w-[200px] lg:flex-col lg:gap-0 lg:overflow-visible lg:pr-[18px] lg:pb-0">
            <Facet
              title="Process"
              data={byProcess}
              active={activeValue('process')}
              onSelect={(v) => setQuery((q) => toggleToken(q, 'process', v))}
            />
            <Facet
              title="Event type"
              data={byEvent}
              active={activeValue('event_type')}
              onSelect={(v) => setQuery((q) => toggleToken(q, 'event_type', v))}
            />
            <Facet
              title="Decision"
              data={byDecision}
              active={activeValue('decision')}
              onSelect={(v) => setQuery((q) => toggleToken(q, 'decision', v))}
              colorFor={(k) => (k === 'allow' ? 'var(--color-success)' : k === 'escalate' ? 'var(--color-warning)' : 'var(--color-danger)')}
            />
          </div>

          <Card className="flex flex-1 flex-col overflow-hidden lg:ml-1">
            <div className="overflow-x-auto">
              <div className="min-w-[720px]">
                <div className="grid grid-cols-[150px_140px_140px_140px_1fr] gap-3.5 border-b border-border px-3.5 py-2.5 font-mono text-[10.5px] font-bold uppercase tracking-wide text-text-muted">
                  <span>Time</span>
                  <span>Event</span>
                  <span>Case</span>
                  <span>Process</span>
                  <span>Message</span>
                </div>
                <div className="max-h-full overflow-y-auto">
                  {!isLoading && rows.length === 0 && (
                    <div className="px-4 py-10 text-center text-sm text-text-muted">No entries match this query.</div>
                  )}
                  {rows.map((row) => {
                    const caseId = caseIdOf(row) || '—'
                    const message = summarize(row)
                    const expanded = expandedId === row.entry_id
                    return (
                      <div key={row.entry_id}>
                        <button
                          onClick={() => setExpandedId(expanded ? null : row.entry_id)}
                          className="grid w-full grid-cols-[150px_140px_140px_140px_1fr] items-center gap-3.5 border-b border-border-subtle px-3.5 py-2.5 text-left text-[12.5px] hover:bg-surface-hover"
                        >
                          <span className="font-mono text-text-muted">{new Date(row.timestamp).toLocaleTimeString()}</span>
                          <span
                            className="w-fit rounded-md px-1.5 py-0.5 text-[10.5px] font-bold"
                            style={{ background: `color-mix(in srgb, ${EVENT_TAG_COLOR[row.event_type] ?? '#5EA8FF'} 14%, transparent)`, color: EVENT_TAG_COLOR[row.event_type] ?? '#5EA8FF' }}
                          >
                            {row.event_type}
                          </span>
                          <span className="truncate font-mono text-accent">{caseId}</span>
                          <span className="truncate text-text-secondary">{row.process}</span>
                          <span className="truncate">{message}</span>
                        </button>
                        {expanded && (
                          <div className="whitespace-pre-line border-b border-border-subtle bg-bg px-3.5 py-3 pl-[164px] font-mono text-[11.5px] text-text-secondary">
                            {JSON.stringify(row.payload, null, 2)}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}

function summarize(entry: AuditLogEntry): string {
  const p = entry.payload as Record<string, unknown>
  switch (entry.event_type) {
    case 'tool_call':
      return `${p.tool_name ?? 'tool'} proposed`
    case 'injection_flag':
      return `Untrusted content flagged${p.snippet ? `: ${String(p.snippet).slice(0, 60)}` : ''}`
    case 'policy_check':
      return entry.scores ? `${entry.scores.decision} — risk ${entry.scores.risk_score}` : 'policy checked'
    case 'approval':
      return `${p.action ?? 'decision'} by ${p.actor ?? 'unknown'}`
    case 'output_claim':
      return `Claim: ${String(p.claim ?? 'unverified output')}`
    default:
      return `${entry.event_type} recorded`
  }
}

function buildHistogram(entries: AuditLogEntry[]) {
  const buckets = 36
  const bars = Array.from({ length: buckets }, () => ({ g: 0, a: 0, r: 0 }))
  if (entries.length === 0) return bars.map(() => ({ g: 6, a: 0, r: 0 }))
  const times = entries.map((e) => new Date(e.timestamp).getTime())
  const min = Math.min(...times)
  const max = Math.max(...times)
  const span = Math.max(max - min, 1)
  const counts = Array.from({ length: buckets }, () => ({ g: 0, a: 0, r: 0 }))
  for (const e of entries) {
    const t = new Date(e.timestamp).getTime()
    const idx = Math.min(buckets - 1, Math.floor(((t - min) / span) * buckets))
    const decision = e.scores?.decision
    if (decision === 'block') counts[idx].r += 1
    else if (decision === 'escalate') counts[idx].a += 1
    else counts[idx].g += 1
  }
  const maxTotal = Math.max(...counts.map((c) => c.g + c.a + c.r), 1)
  return counts.map((c) => ({
    g: (c.g / maxTotal) * 100,
    a: (c.a / maxTotal) * 100,
    r: (c.r / maxTotal) * 100,
  }))
}

function Facet({
  title,
  data,
  active,
  onSelect,
  colorFor,
}: {
  title: string
  data: Record<string, number>
  active: string | null
  onSelect: (value: string) => void
  colorFor?: (key: string) => string
}) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1])
  return (
    <div className="w-[160px] shrink-0 lg:w-auto lg:shrink lg:mb-[18px]">
      <div className="mb-2 text-[10.5px] font-bold uppercase tracking-wide text-text-muted">{title}</div>
      {rows.length === 0 && <div className="px-1.5 text-xs text-text-muted">—</div>}
      {rows.map(([k, v]) => {
        const isActive = active === k.toLowerCase()
        return (
          <button
            key={k}
            onClick={() => onSelect(k)}
            className={cn(
              'flex w-full items-center justify-between rounded-md px-1.5 py-1 text-left text-[12.5px] text-text-secondary hover:bg-surface-hover',
              isActive && 'bg-accent-soft text-accent',
            )}
          >
            <span style={{ color: isActive ? undefined : colorFor?.(k) }} className={cn(!isActive && colorFor && 'font-semibold')}>
              {k}
            </span>
            <span className={cn('text-[11px]', isActive ? 'text-accent' : 'text-text-muted')}>{v}</span>
          </button>
        )
      })}
    </div>
  )
}
