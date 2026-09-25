import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Copy, TriangleAlert } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { ToolsEditor, type ToolsValue } from '../components/process/ToolsEditor'
import { KnowledgeBaseEditor } from '../components/process/KnowledgeBaseEditor'
import { useConfigs, useCreateApplication, useCreateProcess, useUpdateProcess } from '../lib/queries'
import { cn } from '../lib/utils'
import type { AppEnvironment, ApplicationWithKey, ProcessConfig } from '../lib/types'

const STEPS = ['Process', 'Thresholds', 'Policy', 'Connect agent'] as const

const DEFAULT_TOOLS: ToolsValue = { allowedTools: [], disallowedTools: [], approvalThreshold: 60 }

function toToolsValue(cfg: ProcessConfig): ToolsValue {
  return {
    allowedTools: cfg.allowed_tools.map((t) => ({ ...t })),
    disallowedTools: [...cfg.disallowed_tools],
    approvalThreshold: cfg.approval_threshold.risk_score_gte,
  }
}

/** Four-step onboarding wizard: pick or create the process a new agent will
 * be governed by, set its guardrails, give it something to ground against,
 * then issue the agent its key — the steps in that order because each one
 * needs the last (you can't set thresholds on a process that doesn't exist
 * yet, or connect an agent to a process with no policy behind it). */
export function ProcessWizardPage() {
  const navigate = useNavigate()
  const { data: configsResponse } = useConfigs()
  const processes = configsResponse?.processes ?? []
  const createProcess = useCreateProcess()
  const updateProcess = useUpdateProcess()
  const createApp = useCreateApplication()

  // `process` is set once (on create, or on picking an existing one) so the
  // wizard has an id to work with immediately — but step 2's policy editor
  // then mutates that same process's docs via /knowledge/policies, which
  // invalidates the ['configs'] query. Re-deriving from the live list on
  // every render (instead of trusting the one-time snapshot) is what makes
  // a newly written policy actually show up without leaving the wizard.
  const [step, setStep] = useState(0)
  const [mode, setMode] = useState<'new' | 'existing'>('new')
  const [title, setTitle] = useState('')
  const [existingId, setExistingId] = useState('')
  const [processSnapshot, setProcess] = useState<ProcessConfig | null>(null)
  const process = processSnapshot ? (processes.find((p) => p.id === processSnapshot.id) ?? processSnapshot) : null
  const [tools, setTools] = useState<ToolsValue>(DEFAULT_TOOLS)
  const [error, setError] = useState<string | null>(null)

  const [appName, setAppName] = useState('')
  const [environment, setEnvironment] = useState<AppEnvironment>('production')
  const [created, setCreated] = useState<ApplicationWithKey | null>(null)

  async function handleStep1Next() {
    setError(null)
    if (mode === 'existing') {
      const cfg = processes.find((p) => p.id === existingId)
      if (!cfg) {
        setError('Pick a process to continue.')
        return
      }
      setProcess(cfg)
      setTools(toToolsValue(cfg))
      setStep(1)
      return
    }
    if (!title.trim()) {
      setError('Give the new process a name.')
      return
    }
    try {
      const cfg = await createProcess.mutateAsync({ title: title.trim() })
      setProcess(cfg)
      setTools(toToolsValue(cfg))
      setStep(1)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the process.')
    }
  }

  async function handleStep2Next() {
    if (!process) return
    setError(null)
    try {
      await updateProcess.mutateAsync({
        id: process.id,
        input: {
          allowed_tools: tools.allowedTools,
          disallowed_tools: tools.disallowedTools,
          approval_threshold: tools.approvalThreshold,
        },
      })
      setStep(2)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save thresholds.')
    }
  }

  function handleConnect() {
    if (!process || !appName.trim()) return
    setError(null)
    createApp.mutate(
      { name: appName.trim(), environment, process: process.id },
      {
        onSuccess: (app) => setCreated(app),
        onError: (e: Error) => setError(e.message),
      },
    )
  }

  async function copyKey(key: string) {
    try {
      await navigator.clipboard.writeText(key)
    } catch {
      // clipboard permission denied — key is still selectable as text.
    }
  }

  return (
    <>
      <PageHeader
        title="Connect a new agent"
        subtitle="Pick or create the process it's governed by, then set thresholds, policy, and its key — in order"
        showProcessSwitcher={false}
      />

      <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        <div className="mx-auto flex max-w-[640px] flex-col gap-5">
          <ol className="flex items-center gap-2">
            {STEPS.map((label, i) => (
              <li key={label} className="flex flex-1 items-center gap-2">
                <span
                  className={cn(
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold',
                    i < step
                      ? 'bg-success text-[#08111f]'
                      : i === step
                        ? 'bg-accent text-[#08111f]'
                        : 'bg-surface-2 text-text-muted',
                  )}
                >
                  {i < step ? <Check size={13} strokeWidth={3} /> : i + 1}
                </span>
                <span className={cn('text-[12px] font-semibold', i === step ? 'text-text-primary' : 'text-text-muted')}>
                  {label}
                </span>
                {i < STEPS.length - 1 && <span className="h-px flex-1 bg-border" />}
              </li>
            ))}
          </ol>

          {error && (
            <Card className="flex items-center gap-2.5 border-danger/40 bg-danger-soft px-4 py-3 text-[12.5px] text-danger">
              <TriangleAlert size={16} strokeWidth={1.8} className="shrink-0" />
              {error}
            </Card>
          )}

          {step === 0 && (
            <Card className="flex flex-col gap-4 px-5 py-5">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setMode('new')}
                  className={cn(
                    'flex-1 rounded-lg border-[1.5px] px-4 py-2.5 text-[12.5px] font-semibold',
                    mode === 'new' ? 'border-accent bg-accent-soft text-accent' : 'border-border text-text-secondary',
                  )}
                >
                  Create a new process
                </button>
                <button
                  type="button"
                  onClick={() => setMode('existing')}
                  className={cn(
                    'flex-1 rounded-lg border-[1.5px] px-4 py-2.5 text-[12.5px] font-semibold',
                    mode === 'existing'
                      ? 'border-accent bg-accent-soft text-accent'
                      : 'border-border text-text-secondary',
                  )}
                >
                  Use an existing process
                </button>
              </div>

              {mode === 'new' ? (
                <label className="flex flex-col gap-1.5 text-xs font-semibold text-text-secondary">
                  Process name
                  <Input
                    placeholder="Claims Review"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                  <span className="text-[11.5px] font-normal text-text-muted">
                    Writes a new configs/&lt;slug&gt;.yaml the gateway enforces immediately — no code changes.
                  </span>
                </label>
              ) : (
                <div className="flex flex-col gap-2">
                  {processes.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setExistingId(p.id)}
                      className={cn(
                        'flex items-center justify-between rounded-lg border-[1.5px] px-4 py-2.5 text-left text-[12.5px]',
                        existingId === p.id ? 'border-accent bg-accent-soft' : 'border-border hover:bg-surface-hover',
                      )}
                    >
                      <span className="font-semibold">{p.title}</span>
                      <span className="font-mono text-text-muted">{p.id}</span>
                    </button>
                  ))}
                  {processes.length === 0 && (
                    <div className="text-xs text-text-muted">No processes yet — create one instead.</div>
                  )}
                </div>
              )}

              <Button
                variant="accent"
                size="lg"
                className="self-end"
                onClick={handleStep1Next}
                disabled={createProcess.isPending}
              >
                {createProcess.isPending ? 'Creating…' : 'Next'}
              </Button>
            </Card>
          )}

          {step === 1 && process && (
            <Card className="flex flex-col gap-4 px-5 py-5">
              <div className="text-[13px] font-bold text-text-secondary">
                Guardrails for <span className="text-text-primary">{process.title}</span>
              </div>
              <ToolsEditor value={tools} onChange={setTools} />
              <div className="flex justify-between">
                <Button variant="default" onClick={() => setStep(0)}>
                  Back
                </Button>
                <Button variant="accent" onClick={handleStep2Next} disabled={updateProcess.isPending}>
                  {updateProcess.isPending ? 'Saving…' : 'Next'}
                </Button>
              </div>
            </Card>
          )}

          {step === 2 && process && (
            <div className="flex flex-col gap-4">
              <KnowledgeBaseEditor
                processId={process.id}
                processTitle={process.title}
                seedDocs={process.seed_docs}
                uploadedDocs={process.uploaded_docs}
              />
              <div className="flex justify-between">
                <Button variant="default" onClick={() => setStep(1)}>
                  Back
                </Button>
                <Button variant="accent" onClick={() => setStep(3)}>
                  Next
                </Button>
              </div>
            </div>
          )}

          {step === 3 && process && !created && (
            <Card className="flex flex-col gap-4 px-5 py-5">
              <div className="text-[13px] font-bold text-text-secondary">
                Connect the agent that will call <span className="text-text-primary">{process.title}</span>
              </div>
              <label className="flex flex-col gap-1.5 text-xs font-semibold text-text-secondary">
                Agent name
                <Input placeholder="Claims Review Agent" value={appName} onChange={(e) => setAppName(e.target.value)} />
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
              <div className="flex justify-between">
                <Button variant="default" onClick={() => setStep(2)}>
                  Back
                </Button>
                <Button variant="accent" onClick={handleConnect} disabled={!appName.trim() || createApp.isPending}>
                  {createApp.isPending ? 'Connecting…' : 'Create & generate key'}
                </Button>
              </div>
            </Card>
          )}

          {created && (
            <Card className="flex flex-col gap-3 border-success/40 bg-success-soft px-5 py-5">
              <div className="flex items-center gap-2 text-[13px] font-bold text-success">
                <Check size={16} strokeWidth={2.4} />
                {created.name} is connected to {process?.title}
              </div>
              <div className="text-[12.5px] text-text-secondary">This is the only time the full key is shown.</div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <span className="flex-1 overflow-x-auto rounded-md border border-border-subtle bg-bg px-3 py-2 font-mono text-[13px] text-text-primary">
                  {created.api_key}
                </span>
                <Button variant="default" size="sm" onClick={() => copyKey(created.api_key)}>
                  <Copy size={13} strokeWidth={1.8} />
                  Copy
                </Button>
              </div>
              <div className="text-[11.5px] text-text-secondary">
                Set <code className="font-mono">source_app: "{created.source_app}"</code> on requests from this agent.
              </div>
              <Button variant="accent" size="lg" className="self-end" onClick={() => navigate('/applications')}>
                Done
              </Button>
            </Card>
          )}

          {step > 0 && process && (
            <div className="flex items-center gap-2 text-[11.5px] text-text-muted">
              <Badge tone="muted">{process.id}</Badge>
              config_path: <span className="font-mono">{process.config_path}</span>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
