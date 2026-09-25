import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button, buttonStyles } from '../components/ui/Button'
import { useApplications, useRevokeApplication } from '../lib/queries'
import { relativeTime } from '../lib/utils'

export function ApplicationsPage() {
  const { data: apps, isLoading } = useApplications()
  const revokeApp = useRevokeApplication()

  return (
    <>
      <PageHeader
        title="Applications"
        subtitle="Every agent registered with the tower, the process it is governed by, and the key it authenticates with"
        showProcessSwitcher={false}
        actions={
          <Link to="/processes/new" className={buttonStyles({ variant: 'accent' })}>
            <Plus size={14} strokeWidth={2.2} />
            New application
          </Link>
        }
      />

      <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {!isLoading && apps?.length === 0 && (
            <Card className="col-span-full px-6 py-10 text-center text-sm text-text-muted">
              No applications registered yet.
            </Card>
          )}
          {apps?.map((application) => (
            <Card key={application.app_id} className="flex flex-col gap-3.5 px-5 py-[18px]">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-[14.5px] font-bold">{application.name}</div>
                  <div className="mt-0.5 text-[11.5px] capitalize text-text-muted">{application.environment}</div>
                </div>
                <Badge tone={application.status === 'connected' ? 'success' : 'muted'}>{application.status}</Badge>
              </div>

              <div className="flex flex-wrap justify-between gap-2.5 rounded-lg bg-surface-2 px-3 py-2.5">
                <Stat label="Process" value={application.process} mono />
                <Stat label="Requests today" value={String(application.requests_today)} mono />
                <Stat label="Last seen" value={relativeTime(application.last_seen)} />
              </div>

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
                  disabled={application.status === 'revoked' || revokeApp.isPending}
                  onClick={() => revokeApp.mutate(application.app_id)}
                >
                  {application.status === 'revoked' ? 'Revoked' : 'Revoke'}
                </Button>
              </div>
            </Card>
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

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10.5px] font-semibold uppercase text-text-muted">{label}</span>
      <span className={mono ? 'font-mono text-[13px] font-semibold' : 'text-[13px] font-semibold'}>{value}</span>
    </div>
  )
}
