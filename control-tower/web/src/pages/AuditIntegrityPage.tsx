import { CircleCheck, TriangleAlert } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { useAuditEntries, useDemoTamper, useVerifyAudit } from '../lib/queries'
import { cn } from '../lib/utils'

function shortHash(h: string): string {
  if (!h) return '—'
  return h.length > 12 ? `${h.slice(0, 4)}...${h.slice(-4)}` : h
}

export function AuditIntegrityPage() {
  const { data: entriesResponse, isLoading } = useAuditEntries({ limit: 200 })
  const { data: verify } = useVerifyAudit()
  const tamper = useDemoTamper()

  const rows = entriesResponse?.entries ?? []
  const tampered = !!verify && !verify.valid
  const brokenEntryId = verify?.first_invalid_entry_id ?? null

  return (
    <>
      <PageHeader
        title="Audit & integrity"
        subtitle="Hash-chained, append-only log — entry_hash = sha256(prev_hash + payload + timestamp)"
        showProcessSwitcher={false}
        actions={
          <div className="flex gap-2.5">
            <Button variant="default" disabled={tamper.isPending} onClick={() => tamper.mutate(!tampered)}>
              {tamper.isPending ? 'Working…' : tampered ? 'Undo tamper demo' : 'Simulate tamper (demo)'}
            </Button>
          </div>
        }
      />

      <div className="flex flex-1 flex-col gap-[18px] overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        <Card
          className={cn(
            'flex items-center gap-3 px-5 py-4',
            tampered ? 'border-danger/40 bg-danger-soft' : 'border-success/40 bg-success-soft',
          )}
        >
          {tampered ? (
            <TriangleAlert size={20} strokeWidth={1.7} className="shrink-0 text-danger" />
          ) : (
            <CircleCheck size={20} strokeWidth={1.7} className="shrink-0 text-success" />
          )}
          <div>
            <div className={cn('text-[13.5px] font-bold', tampered ? 'text-danger' : 'text-success')}>
              {tampered
                ? `Chain broken at entry ${brokenEntryId ?? '—'}`
                : verify
                  ? `Chain intact — ${verify.entry_count} entries verified`
                  : 'Chain intact'}
            </div>
            <div className="mt-0.5 text-[12.5px] text-text-secondary">
              {tampered
                ? 'This entry’s stored hash was overwritten server-side (a real UPDATE against data/audit.db, not a UI simulation) — GET /audit/verify genuinely fails until it is restored.'
                : 'Every entry_hash matches sha256(prev_hash + payload + timestamp) for its row. No silent edits detected.'}
            </div>
          </div>
        </Card>

        <Card className="flex flex-1 flex-col overflow-hidden">
          <div className="border-b border-border px-[18px] py-3.5 text-sm font-bold">
            Log entries {entriesResponse && <span className="font-normal text-text-muted">({entriesResponse.total} total)</span>}
          </div>
          <div className="overflow-auto">
            <table className="w-full min-w-[720px] border-collapse">
              <thead>
                <tr className="text-left text-[10.5px] font-bold uppercase tracking-wide text-text-muted">
                  <th className="w-[130px] border-b border-border px-4 py-2.5">Entry</th>
                  <th className="w-[150px] border-b border-border px-4 py-2.5">Event</th>
                  <th className="w-[120px] border-b border-border px-4 py-2.5">Process</th>
                  <th className="border-b border-border px-4 py-2.5">prev_hash</th>
                  <th className="border-b border-border px-4 py-2.5">entry_hash</th>
                  <th className="w-[100px] border-b border-border px-4 py-2.5">Time</th>
                </tr>
              </thead>
              <tbody>
                {!isLoading && rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-sm text-text-muted">
                      No audit entries yet — submit or seed a case first.
                    </td>
                  </tr>
                )}
                {rows.map((row) => {
                  const broken = row.entry_id === brokenEntryId
                  return (
                    <tr key={row.entry_id} className="border-b border-border-subtle text-[12.5px] last:border-none">
                      <td className="px-4 py-3 font-mono text-text-secondary">{shortHash(row.entry_id)}</td>
                      <td className="px-4 py-3">
                        <span className="rounded-md bg-surface-2 px-2 py-1 text-text-secondary">{row.event_type}</span>
                      </td>
                      <td className="px-4 py-3 text-text-secondary">{row.process}</td>
                      <td className="px-4 py-3 font-mono text-text-muted">{shortHash(row.prev_hash)}</td>
                      <td className={cn('px-4 py-3 font-mono', broken ? 'font-bold text-danger' : 'text-text-secondary')}>
                        {broken ? 'MISMATCH' : shortHash(row.entry_hash)}
                      </td>
                      <td className="px-4 py-3 text-text-muted">{new Date(row.timestamp).toLocaleTimeString()}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  )
}
