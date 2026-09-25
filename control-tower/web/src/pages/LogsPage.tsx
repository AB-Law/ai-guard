import { useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { ChevronDown, Search } from 'lucide-react'
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

const QUICK_RANGES: { key: string; label: string; minutes: number | null; fetchLimit: number }[] = [
  { key: 'live', label: 'Live', minutes: null, fetchLimit: 200 },
  { key: '15m', label: '15 mins', minutes: 15, fetchLimit: 200 },
  { key: '1h', label: '1 hour', minutes: 60, fetchLimit: 300 },
  { key: '4h', label: '4 hours', minutes: 240, fetchLimit: 500 },
  { key: '1d', label: '1 day', minutes: 24 * 60, fetchLimit: 800 },
  { key: '1w', label: '1 week', minutes: 7 * 24 * 60, fetchLimit: 1500 },
]

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
  const [timeRange, setTimeRange] = useState<{ start: number; end: number } | null>(null)
  const [quickRange, setQuickRange] = useState('live')
  const [showRangeMenu, setShowRangeMenu] = useState(false)
  const [hover, setHover] = useState<{ idx: number; x: number; y: number } | null>(null)
  const [dragStart, setDragStart] = useState<number | null>(null)
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const histRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const activeRange = QUICK_RANGES.find((r) => r.key === quickRange) ?? QUICK_RANGES[0]
  const { data: entriesResponse, isLoading } = useAuditEntries({ limit: activeRange.fetchLimit }, { live })
  const entries = useMemo(() => entriesResponse?.entries ?? [], [entriesResponse])

  function selectQuickRange(key: string) {
    setQuickRange(key)
    setTimeRange(null)
    setShowRangeMenu(false)
  }

  const tokens = useMemo(() => parseQuery(query), [query])
  const tokenRows = useMemo(() => entries.filter((e) => matchesTokens(e, tokens)), [entries, tokens])

  // "Show logs for last" narrows to a rolling window ending at "now". In a
  // live system that's the wall clock; against this static/replayed demo
  // data set (seeded once, not advancing) it's anchored to the newest entry
  // instead, so "15 mins"/"1 hour" still show the tail of the log rather than
  // nothing just because real time has since moved on.
  const latestEntryMs = useMemo(
    () => entries.reduce((max, e) => Math.max(max, new Date(e.timestamp).getTime()), 0),
    [entries],
  )
  const anchorNow = latestEntryMs || Date.now()
  const quickWindow = activeRange.minutes == null ? null : { start: anchorNow - activeRange.minutes * 60000, end: anchorNow }
  const quickRows = useMemo(
    () => (quickWindow ? tokenRows.filter((e) => inTimeRange(e, quickWindow)) : tokenRows),
    [tokenRows, quickWindow?.start, quickWindow?.end],
  )
  const rows = useMemo(
    () => (timeRange ? quickRows.filter((e) => inTimeRange(e, timeRange)) : quickRows),
    [quickRows, timeRange],
  )

  // Each facet's own counts ignore its own active filter (so you can still see
  // — and click — the other values), but respect every other active filter,
  // the quick range and the selected time range.
  function facetCounts(field: Field): Record<string, number> {
    const scoped = entries.filter(
      (e) =>
        matchesTokens(e, tokens.filter((t) => t.field !== field)) &&
        (!quickWindow || inTimeRange(e, quickWindow)) &&
        (!timeRange || inTimeRange(e, timeRange)),
    )
    const out: Record<string, number> = {}
    for (const e of scoped) {
      const v = fieldValue(e, field)
      if (!v) continue
      out[v] = (out[v] ?? 0) + 1
    }
    return out
  }
  const byProcess = useMemo(() => facetCounts('process'), [entries, tokens, timeRange, quickWindow?.start, quickWindow?.end])
  const byEvent = useMemo(() => facetCounts('event_type'), [entries, tokens, timeRange, quickWindow?.start, quickWindow?.end])
  const byDecision = useMemo(() => facetCounts('decision'), [entries, tokens, timeRange, quickWindow?.start, quickWindow?.end])

  const activeValue = (field: Field): string | null => tokens.find((t) => t.field === field)?.value ?? null

  // The histogram always shows the full quick-range window — a click/drag
  // selection just highlights a sub-range of it rather than shrinking it —
  // so you can see what you filtered out and change it.
  const bars = useMemo(() => buildHistogram(quickRows), [quickRows])

  function bucketRange(idx: number): { start: number; end: number } | null {
    const b = bars[idx]
    if (!b) return null
    return { start: b.start, end: b.end }
  }

  function selectDragRange(fromIdx: number, toIdx: number) {
    const lo = Math.min(fromIdx, toIdx)
    const hi = Math.max(fromIdx, toIdx)
    const start = bars[lo]?.start
    const end = bars[hi]?.end
    if (start === undefined || end === undefined) return
    setTimeRange({ start, end })
  }

  function bucketIdxAtClientX(clientX: number): number | null {
    const el = histRef.current
    if (!el || bars.length === 0) return null
    const rect = el.getBoundingClientRect()
    const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
    return Math.min(bars.length - 1, Math.floor(frac * bars.length))
  }

  function handleBarMouseDown(idx: number) {
    setDragStart(idx)
    setDragIdx(idx)
  }

  function handleHistMouseMove(e: { clientX: number; clientY: number }) {
    if (dragStart !== null) {
      const idx = bucketIdxAtClientX(e.clientX)
      if (idx !== null) setDragIdx(idx)
      return
    }
    const idx = bucketIdxAtClientX(e.clientX)
    if (idx !== null) setHover({ idx, x: e.clientX, y: e.clientY })
  }

  function handleHistMouseUp() {
    if (dragStart !== null && dragIdx !== null) {
      if (dragStart === dragIdx) {
        // Plain click on a single bucket: toggle its time range.
        const r = bucketRange(dragStart)
        if (r) {
          setTimeRange((cur) => (cur && cur.start === r.start && cur.end === r.end ? null : r))
        }
      } else {
        selectDragRange(dragStart, dragIdx)
      }
    }
    setDragStart(null)
    setDragIdx(null)
  }

  function handleHistMouseLeave() {
    setHover(null)
    if (dragStart !== null) {
      handleHistMouseUp()
    }
  }

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
          <div className="flex items-center gap-2.5">
            <div className="relative">
              <button
                data-testid="quick-range-button"
                onClick={() => setShowRangeMenu((v) => !v)}
                onBlur={() => setTimeout(() => setShowRangeMenu(false), 120)}
                className={cn(
                  'flex items-center gap-2 rounded-lg border-2 px-4 py-2.5 text-[14px] font-bold',
                  showRangeMenu
                    ? 'border-accent bg-accent-soft text-accent'
                    : 'border-accent-border bg-accent-soft text-accent hover:bg-accent-soft/80',
                )}
              >
                <span className="text-text-muted">Last:</span> {activeRange.label}
                <ChevronDown size={16} strokeWidth={2.5} className={cn('transition-transform', showRangeMenu && 'rotate-180')} />
              </button>
              {showRangeMenu && (
                <Card className="absolute right-0 top-[calc(100%+6px)] z-10 flex w-44 flex-col overflow-hidden py-1.5 shadow-xl">
                  {QUICK_RANGES.map((r) => (
                    <button
                      key={r.key}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => selectQuickRange(r.key)}
                      className={cn(
                        'px-4 py-2.5 text-left text-[13.5px] font-semibold',
                        r.key === quickRange ? 'bg-accent-soft text-accent' : 'text-text-secondary hover:bg-surface-hover',
                      )}
                    >
                      {r.label}
                    </button>
                  ))}
                </Card>
              )}
            </div>
            <button
              onClick={() => setLive((v) => !v)}
              className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3.5 py-2 text-[12.5px] font-bold"
              style={{ color: live ? 'var(--color-success)' : 'var(--color-text-muted)' }}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
              {live ? 'Live tail' : 'Paused'}
            </button>
          </div>
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

        {timeRange && (
          <div data-testid="time-range-chip" className="mb-2 flex items-center gap-2 text-[11.5px] text-text-secondary">
            <span className="rounded-md bg-accent-soft px-2 py-1 font-mono text-accent">
              {formatClock(timeRange.start)} – {formatClock(timeRange.end)}
            </span>
            <button
              onClick={() => setTimeRange(null)}
              className="rounded-md px-1.5 py-0.5 text-text-muted hover:bg-surface-hover hover:text-text-primary"
            >
              Clear time filter ✕
            </button>
          </div>
        )}
        <div className="relative">
          <Card
            ref={histRef}
            data-testid="histogram"
            className="mb-3.5 flex h-16 select-none items-end gap-[3px] px-4 py-3"
            onMouseMove={handleHistMouseMove}
            onMouseUp={handleHistMouseUp}
            onMouseLeave={handleHistMouseLeave}
          >
            {bars.map((b, i) => {
              const dragLo = dragStart !== null && dragIdx !== null ? Math.min(dragStart, dragIdx) : null
              const dragHi = dragStart !== null && dragIdx !== null ? Math.max(dragStart, dragIdx) : null
              const inDrag = dragLo !== null && dragHi !== null && i >= dragLo && i <= dragHi
              const inSelected = timeRange !== null && b.start >= timeRange.start && b.end <= timeRange.end
              const highlighted = inDrag || inSelected
              return (
                <div
                  key={i}
                  data-testid={`hist-bar-${i}`}
                  onMouseDown={() => handleBarMouseDown(i)}
                  className={cn(
                    'flex h-full flex-1 flex-col-reverse gap-px rounded-[1px] cursor-pointer',
                    highlighted && 'bg-accent-soft',
                  )}
                >
                  <div
                    data-testid={`hist-decision-allow-${i}`}
                    className="rounded-[1px] bg-success"
                    style={{ height: `${b.g}%`, opacity: highlighted || !timeRange ? 1 : 0.35 }}
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation()
                      setQuery((q) => toggleToken(q, 'decision', 'allow'))
                    }}
                  />
                  <div
                    data-testid={`hist-decision-escalate-${i}`}
                    className="rounded-[1px] bg-warning"
                    style={{ height: `${b.a}%`, opacity: highlighted || !timeRange ? 1 : 0.35 }}
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation()
                      setQuery((q) => toggleToken(q, 'decision', 'escalate'))
                    }}
                  />
                  <div
                    data-testid={`hist-decision-block-${i}`}
                    className="rounded-[1px] bg-danger"
                    style={{ height: `${b.r}%`, opacity: highlighted || !timeRange ? 1 : 0.35 }}
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation()
                      setQuery((q) => toggleToken(q, 'decision', 'block'))
                    }}
                  />
                </div>
              )
            })}
          </Card>
          {hover && dragStart === null && bars[hover.idx] && (
            <div
              data-testid="hist-tooltip"
              className="pointer-events-none fixed z-20 rounded-md border border-border bg-surface px-2.5 py-1.5 text-[11.5px] shadow-lg"
              style={{ left: hover.x + 12, top: hover.y - 44 }}
            >
              <div className="font-mono text-text-muted">
                {formatClock(bars[hover.idx].start)} – {formatClock(bars[hover.idx].end)}
              </div>
              <div className="mt-0.5 flex items-center gap-2.5">
                <span className="text-success">allow {bars[hover.idx].counts.g}</span>
                <span className="text-warning">escalate {bars[hover.idx].counts.a}</span>
                <span className="text-danger">block {bars[hover.idx].counts.r}</span>
              </div>
            </div>
          )}
        </div>

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
                          <div
                            data-testid={`expanded-payload-${row.entry_id}`}
                            className="whitespace-pre-line border-b border-border-subtle bg-bg px-3.5 py-3 pl-[164px] font-mono text-[11.5px] text-text-secondary"
                          >
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

function formatClock(ms: number): string {
  return new Date(ms).toLocaleTimeString()
}

interface HistBucket {
  start: number
  end: number
  g: number
  a: number
  r: number
  counts: { g: number; a: number; r: number }
}

function inTimeRange(entry: AuditLogEntry, range: { start: number; end: number }): boolean {
  const t = new Date(entry.timestamp).getTime()
  return t >= range.start && t <= range.end
}

// Round, human-legible bucket widths (Datadog-style "auto interval") instead
// of dividing the time span into an arbitrary number of equal slices.
const NICE_STEPS_MS = [
  1000, 5000, 10000, 15000, 30000, // 1s, 5s, 10s, 15s, 30s
  60000, 5 * 60000, 10 * 60000, 15 * 60000, 30 * 60000, // 1m, 5m, 10m, 15m, 30m
  3600000, 3 * 3600000, 6 * 3600000, 12 * 3600000, // 1h, 3h, 6h, 12h
  86400000, // 1d
]
const TARGET_BUCKETS = 36

function pickBucketStep(spanMs: number): number {
  for (const step of NICE_STEPS_MS) {
    if (spanMs / step <= TARGET_BUCKETS) return step
  }
  return NICE_STEPS_MS[NICE_STEPS_MS.length - 1]
}

function buildHistogram(entries: AuditLogEntry[]): HistBucket[] {
  const now = Date.now()
  if (entries.length === 0) {
    return Array.from({ length: TARGET_BUCKETS }, (_, i) => ({
      start: now + i,
      end: now + i + 1,
      g: 6,
      a: 0,
      r: 0,
      counts: { g: 0, a: 0, r: 0 },
    }))
  }
  const times = entries.map((e) => new Date(e.timestamp).getTime())
  const min = Math.min(...times)
  const max = Math.max(...times)
  const step = pickBucketStep(Math.max(max - min, 1))
  const start = Math.floor(min / step) * step
  const buckets = Math.max(1, Math.ceil((max - start + 1) / step))
  const counts = Array.from({ length: buckets }, () => ({ g: 0, a: 0, r: 0 }))
  for (const e of entries) {
    const t = new Date(e.timestamp).getTime()
    const idx = Math.min(buckets - 1, Math.floor((t - start) / step))
    const decision = e.scores?.decision
    if (decision === 'block') counts[idx].r += 1
    else if (decision === 'escalate') counts[idx].a += 1
    else counts[idx].g += 1
  }
  const maxTotal = Math.max(...counts.map((c) => c.g + c.a + c.r), 1)
  return counts.map((c, i) => ({
    start: start + i * step,
    end: start + (i + 1) * step,
    g: (c.g / maxTotal) * 100,
    a: (c.a / maxTotal) * 100,
    r: (c.r / maxTotal) * 100,
    counts: c,
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
