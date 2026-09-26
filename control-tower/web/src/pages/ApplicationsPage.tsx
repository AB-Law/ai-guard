import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button, buttonStyles } from '../components/ui/Button'
import { useApplications, useRevokeApplication } from '../lib/queries'
import type { AppEnvironment, AppHealth, Application, AppStatus } from '../lib/types'
import { cn, relativeTime } from '../lib/utils'

type StatusFilter = 'all' | AppStatus | AppHealth

function activityLabel(app: Application): string {
  if (app.status === 'revoked') return 'revoked'
  return app.health ?? 'never_seen'
}

function matchesStatus(app: Application, filter: StatusFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'revoked' || filter === 'connected') return app.status === filter
  return activityLabel(app) === filter
}

function healthTone(app: Application): 'success' | 'warning' | 'muted' | 'danger' {
  if (app.status === 'revoked') return 'muted'
  switch (app.health) {
    case 'online':
      return 'success'
    case 'stale':
      return 'warning'
    case 'offline':
      return 'danger'
    default:
      return 'muted'
  }
}

export function ApplicationsPage() {
  const { data: apps, isLoading } = useApplications()
  const revokeApp = useRevokeApplication()
  const [environment, setEnvironment] = useState<'all' | AppEnvironment>('all')
  const [process, setProcess] = useState('all')
  const [status, setStatus] = useState<StatusFilter>('all')

  const processes = useMemo(() => {
    const set = new Set((apps ?? []).map((a) => a.process))
    return [...set].sort()
  }, [apps])

  const filtered = useMemo(() => {
    return (apps ?? []).filter((app) => {
      if (environment !== 'all' && app.environment !== environment) return false
      if (process !== 'all' && app.process !== process) return false
      return matchesStatus(app, status)
    })
  }, [apps, environment, process, status])

  return (
    <>
      <PageHeader
        title="Applications"
        subtitle="Every agent registered with the tower — inventory metadata, last activity, and the key it authenticates with"
        showProcessSwitcher={false}
        actions={
          <Link to="/processes/new" className={buttonStyles({ variant: 'accent' })}>
            <Plus size={14} strokeWidth={2.2} />
            New application
          </Link>
        }
      />

      <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        <div className="mb-4 flex flex-wrap gap-2">
          <FilterSelect
            label="Environment"
            value={environment}
            onChange={(v) => setEnvironment(v as 'all' | AppEnvironment)}
            options={[
              { value: 'all', label: 'All environments' },
              { value: 'production', label: 'Production' },
              { value: 'staging', label: 'Staging' },
            ]}
          />
          <FilterSelect
            label="Process"
            value={process}
            onChange={setProcess}
            options={[
              { value: 'all', label: 'All processes' },
              ...processes.map((p) => ({ value: p, label: p })),
            ]}
          />
          <FilterSelect
            label="Status"
            value={status}
            onChange={(v) => setStatus(v as StatusFilter)}
            options={[
              { value: 'all', label: 'All statuses' },
              { value: 'online', label: 'Online' },
              { value: 'stale', label: 'Stale' },
              { value: 'offline', label: 'Offline' },
              { value: 'never_seen', label: 'Never seen' },
              { value: 'connected', label: 'Connected' },
              { value: 'revoked', label: 'Revoked' },
            ]}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {!isLoading && filtered.length === 0 && (
            <Card className="col-span-full px-6 py-10 text-center text-sm text-text-muted">
              {(apps?.length ?? 0) === 0
                ? 'No applications registered yet.'
                : 'No applications match the current filters.'}
            </Card>
          )}
          {filtered.map((application) => (
            <ApplicationCard
              key={application.app_id}
              application={application}
              onRevoke={() => revokeApp.mutate(application.app_id)}
              revokePending={revokeApp.isPending}
            />
          ))}

          <Link
            to="/processes/new"
            className="flex min-h-[220px] cursor-pointer flex-col items-center justify-center gap-2.5 rounded-xl border-[1.5px] border-dashed border-border bg-surface px-5 py-[18px] text-text-secondary hover:border-accent hover:text-text-primary"
          >
            <Plus size={22} strokeWidth={1.6} />
            <div className="text-[13px] font-bold text-text-primary">Connect a new agent</div>
            <div className="max-w-[200px] text-center text-[11.5px] leading-relaxed">
              Walks you through picking a process, thresholds, policy, and a scoped API key.
            </div>
          </Link>
        </div>
      </div>
    </>
  )
}

function ApplicationCard({
  application,
  onRevoke,
  revokePending,
}: {
  application: Application
  onRevoke: () => void
  revokePending: boolean
}) {
  const lastActivity = application.last_seen_at ?? application.last_seen ?? null
  const declaredTools = application.tools ?? []
  const capabilities = application.capabilities ?? []
  const mcpServers = application.mcp_servers ?? []
  const observedTools = application.observed_tools ?? []

  return (
    <Card className="flex flex-col gap-3.5 px-5 py-[18px]">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[14.5px] font-bold">{application.name}</div>
          <div className="mt-0.5 text-[11.5px] capitalize text-text-muted">{application.environment}</div>
          {(application.owner || application.team) && (
            <div className="mt-1 text-[11.5px] text-text-secondary">
              {[application.owner, application.team].filter(Boolean).join(' · ')}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge tone={healthTone(application)}>{activityLabel(application)}</Badge>
          {application.status === 'revoked' ? null : (
            <span className="text-[10px] uppercase text-text-muted">{application.status}</span>
          )}
        </div>
      </div>

      {application.description && (
        <p className="line-clamp-2 text-[12px] leading-relaxed text-text-secondary">{application.description}</p>
      )}

      <div className="flex flex-wrap justify-between gap-2.5 rounded-lg bg-surface-2 px-3 py-2.5">
        <Stat label="Process" value={application.process} mono />
        <Stat label="Requests today" value={String(application.requests_today)} mono />
        <Stat label="Last seen" value={relativeTime(lastActivity)} />
      </div>

      {(application.framework || application.runtime) && (
        <div className="flex flex-wrap gap-2 text-[11.5px] text-text-secondary">
          {application.framework && <span>Framework: {application.framework}</span>}
          {application.runtime && <span>Runtime: {application.runtime}</span>}
        </div>
      )}

      {(declaredTools.length > 0 || capabilities.length > 0) && (
        <TagBlock
          label="Declared tools / capabilities"
          values={[...declaredTools, ...capabilities]}
        />
      )}

      {mcpServers.length > 0 && (
        <div>
          <div className="mb-1.5 text-[10.5px] font-semibold uppercase text-text-muted">
            Declared MCP servers
          </div>
          <p className="mb-1.5 text-[11px] text-text-muted">
            Self-reported connections — not discovered by scanning a host.
          </p>
          <ul className="flex flex-col gap-1.5">
            {mcpServers.map((server) => (
              <li
                key={`${server.name}-${server.url ?? ''}`}
                className="rounded-md border border-border-subtle bg-bg px-2.5 py-2 text-[12px]"
              >
                <div className="font-semibold text-text-primary">{server.name}</div>
                {server.url && <div className="font-mono text-[11px] text-text-muted">{server.url}</div>}
                {(server.tools?.length ?? 0) > 0 && (
                  <div className="mt-1 text-[11px] text-text-secondary">
                    Tools: {server.tools.join(', ')}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {observedTools.length > 0 && (
        <TagBlock
          label="Observed traffic (tools)"
          values={observedTools}
          hint="From authenticated cases — not MCP discovery."
        />
      )}

      <div>
        <div className="mb-1.5 text-[10.5px] font-semibold uppercase text-text-muted">API key</div>
        <span className="block truncate rounded-md border border-border-subtle bg-bg px-2.5 py-2 font-mono text-[12.5px] text-text-secondary">
          {application.key_display}
        </span>
      </div>

      <div className="flex justify-end">
        <Button
          variant="danger-outline"
          size="sm"
          disabled={application.status === 'revoked' || revokePending}
          onClick={onRevoke}
        >
          {application.status === 'revoked' ? 'Revoked' : 'Revoke'}
        </Button>
      </div>
    </Card>
  )
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <label className="flex flex-col gap-1 text-[10.5px] font-semibold uppercase text-text-muted">
      {label}
      <select
        className={cn(
          'min-w-[140px] rounded-lg border border-border bg-surface px-2.5 py-2 text-[12.5px] font-semibold normal-case text-text-primary',
        )}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function TagBlock({
  label,
  values,
  hint,
}: {
  label: string
  values: string[]
  hint?: string
}) {
  return (
    <div>
      <div className="mb-1.5 text-[10.5px] font-semibold uppercase text-text-muted">{label}</div>
      {hint && <p className="mb-1.5 text-[11px] text-text-muted">{hint}</p>}
      <div className="flex flex-wrap gap-1.5">
        {values.map((v) => (
          <span
            key={v}
            className="rounded-md border border-border-subtle bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-text-secondary"
          >
            {v}
          </span>
        ))}
      </div>
    </div>
  )
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10.5px] font-semibold uppercase text-text-muted">{label}</span>
      <span className={mono ? 'font-mono text-[13px] font-semibold' : 'text-[13px] font-semibold'}>{value}</span>
    </div>
  )
}
