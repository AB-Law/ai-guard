import { useState, type FormEvent } from 'react'
import { Copy, Plus, TriangleAlert, X } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { useApplications, useConfigs, useCreateApplication, useRevokeApplication } from '../lib/queries'
import { relativeTime } from '../lib/utils'
import type { AppEnvironment, ApplicationWithKey } from '../lib/types'

export function ApplicationsPage() {
  const { data: apps, isLoading } = useApplications()
  const { data: configsResponse } = useConfigs()
  const processes = configsResponse?.processes ?? []
  const createApp = useCreateApplication()
  const revokeApp = useRevokeApplication()

  const [creating, setCreating] = useState(false)
  const [justCreated, setJustCreated] = useState<ApplicationWithKey | null>(null)
  const [name, setName] = useState('')
  const [environment, setEnvironment] = useState<AppEnvironment>('production')
  const [process, setProcess] = useState('')

  function handleCreate(e: FormEvent) {
    e.preventDefault()
    if (!name.trim() || !process) return
    createApp.mutate(
      { name: name.trim(), environment, process },
      {
        onSuccess: (created) => {
          setJustCreated(created)
          setCreating(false)
          setName('')
          setProcess('')
        },
      },
    )
  }

  async function copyKey(key: string) {
    try {
      await navigator.clipboard.writeText(key)
    } catch {
      // clipboard permission denied — user can still select the text manually.
    }
  }

  return (
    <>
      <PageHeader
        title="Applications"
        subtitle="Every agent registered with the tower, the process it is governed by, and the key it authenticates with"
        showProcessSwitcher={false}
        actions={
          <Button variant="accent" onClick={() => setCreating((v) => !v)}>
            <Plus size={14} strokeWidth={2.2} />
            New application
          </Button>
        }
      />

      <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        {justCreated && (
          <Card className="mb-5 flex items-start gap-3 border-warning/40 bg-warning-soft px-5 py-4">
            <TriangleAlert size={18} strokeWidth={1.7} className="mt-0.5 shrink-0 text-warning" />
            <div className="flex-1">
              <div className="text-[13px] font-bold text-warning">
                {justCreated.name} connected — this is the only time the full key is shown
              </div>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
                <span className="flex-1 overflow-x-auto rounded-md border border-border-subtle bg-bg px-3 py-2 font-mono text-[13px] text-text-primary">
                  {justCreated.api_key}
                </span>
                <Button variant="default" size="sm" onClick={() => copyKey(justCreated.api_key)}>
                  <Copy size={13} strokeWidth={1.8} />
                  Copy
                </Button>
              </div>
              <div className="mt-1.5 text-[11.5px] text-text-secondary">
                Set <code className="font-mono">source_app: "{justCreated.source_app}"</code> on requests from this
                agent so its traffic is attributed here.
              </div>
            </div>
            <button onClick={() => setJustCreated(null)} className="text-text-muted hover:text-text-primary">
              <X size={16} strokeWidth={2} />
            </button>
          </Card>
        )}

        {creating && (
          <Card className="mb-5 px-5 py-[18px]">
            <form onSubmit={handleCreate} className="flex flex-col flex-wrap gap-3 sm:flex-row sm:items-end">
              <label className="flex min-w-[180px] flex-1 flex-col gap-1.5 text-xs font-semibold text-text-secondary">
                Name
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Claims Review Agent" required />
              </label>
              <label className="flex flex-col gap-1.5 text-xs font-semibold text-text-secondary">
                Environment
                <select
                  value={environment}
                  onChange={(e) => setEnvironment(e.target.value as AppEnvironment)}
                  className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-sm text-text-primary outline-none focus:border-accent sm:w-auto"
                >
                  <option value="production">Production</option>
                  <option value="staging">Staging</option>
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-xs font-semibold text-text-secondary">
                Process
                <select
                  value={process}
                  onChange={(e) => setProcess(e.target.value)}
                  required
                  className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-sm text-text-primary outline-none focus:border-accent sm:w-auto"
                >
                  <option value="" disabled>
                    Select…
                  </option>
                  {processes.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.title}
                    </option>
                  ))}
                </select>
              </label>
              <Button type="submit" variant="accent" disabled={createApp.isPending}>
                {createApp.isPending ? 'Creating…' : 'Create & generate key'}
              </Button>
            </form>
          </Card>
        )}

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

          <Card
            onClick={() => setCreating(true)}
            className="flex min-h-[220px] cursor-pointer flex-col items-center justify-center gap-2.5 border-dashed px-5 py-[18px] text-text-secondary hover:border-accent hover:text-text-primary"
          >
            <Plus size={22} strokeWidth={1.6} />
            <div className="text-[13px] font-bold text-text-primary">Connect a new agent</div>
            <div className="max-w-[200px] text-center text-[11.5px] leading-relaxed">
              Assign it a process config and generate a scoped API key — no code changes to the tower.
            </div>
          </Card>
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
