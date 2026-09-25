import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Copy, TriangleAlert } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { ToolsEditor, type ToolsValue } from '../components/process/ToolsEditor'
import { KnowledgeBaseEditor } from '../components/process/KnowledgeBaseEditor'
import {
  useConfigs,
  useCreateApplication,
  useCreateProcessFromSchema,
  useProcessSchema,
  useUpdateProcess,
} from '../lib/queries'
import { ProcessValidationError, type ProcessConfigPayload } from '../lib/api'
import {
  evidenceEnumFromSchema,
  fieldErrorMap,
  slugifyProcessId,
  validateAgainstSchema,
} from '../lib/processSchema'
import { cn } from '../lib/utils'
import type { AppEnvironment, ApplicationWithKey, ProcessConfig } from '../lib/types'

const STEPS = ['Process', 'Policy', 'Connect agent'] as const

const DEFAULT_TOOLS: ToolsValue = {
  allowedTools: [],
  disallowedTools: [],
  approvalThreshold: 60,
  requiredEvidenceDocs: [],
}

function toToolsValue(cfg: ProcessConfig): ToolsValue {
  return {
    allowedTools: cfg.allowed_tools.map((t) => ({ ...t })),
    disallowedTools: [...cfg.disallowed_tools],
    approvalThreshold: cfg.approval_threshold.risk_score_gte,
    requiredEvidenceDocs: [],
  }
}

function buildPayload(
  processId: string,
  title: string,
  tools: ToolsValue,
): ProcessConfigPayload {
  return {
    process: processId,
    title: title.trim() || null,
    allowed_tools: tools.allowedTools,
    disallowed_tools: tools.disallowedTools,
    required_evidence_docs: tools.requiredEvidenceDocs ?? [],
    approval_threshold: { risk_score_gte: tools.approvalThreshold },
    knowledge_base_paths: [],
  }
}

/** Three-step onboarding: schema-driven process config (or pick existing),
 * policy KB, then connect an agent with an API key. */
export function ProcessWizardPage() {
  const navigate = useNavigate()
  const { data: configsResponse } = useConfigs()
  const { data: schema } = useProcessSchema()
  const processes = configsResponse?.processes ?? []
  const createFromSchema = useCreateProcessFromSchema()
  const updateProcess = useUpdateProcess()
  const createApp = useCreateApplication()

  const evidenceOptions = useMemo(
    () => (schema ? evidenceEnumFromSchema(schema) : []),
    [schema],
  )

  const [step, setStep] = useState(0)
  const [mode, setMode] = useState<'new' | 'existing'>('new')
  const [title, setTitle] = useState('')
  const [processId, setProcessId] = useState('')
  const [processIdTouched, setProcessIdTouched] = useState(false)
  const [existingId, setExistingId] = useState('')
  const [processSnapshot, setProcess] = useState<ProcessConfig | null>(null)
  const process = processSnapshot
    ? (processes.find((p) => p.id === processSnapshot.id) ?? processSnapshot)
    : null
  const [tools, setTools] = useState<ToolsValue>(DEFAULT_TOOLS)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const [appName, setAppName] = useState('')
  const [environment, setEnvironment] = useState<AppEnvironment>('production')
  const [created, setCreated] = useState<ApplicationWithKey | null>(null)

  function onTitleChange(next: string) {
    setTitle(next)
    if (!processIdTouched) setProcessId(slugifyProcessId(next))
  }

  function runInlineValidation(payload: ProcessConfigPayload): boolean {
    if (!schema) return true
    const errors = validateAgainstSchema(schema, payload)
    if (errors.length === 0) {
      setFieldErrors({})
      return true
    }
    setFieldErrors(fieldErrorMap(errors))
    return false
  }

  async function handleStep0Next() {
    setError(null)
    setFieldErrors({})
    if (mode === 'existing') {
      const cfg = processes.find((p) => p.id === existingId)
      if (!cfg) {
        setError('Pick a process to continue.')
        return
      }
      try {
        await updateProcess.mutateAsync({
          id: cfg.id,
          input: {
            allowed_tools: tools.allowedTools,
            disallowed_tools: tools.disallowedTools,
            approval_threshold: tools.approvalThreshold,
          },
        })
        setProcess(cfg)
        setStep(1)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not save thresholds.')
      }
      return
    }

    const id = processId.trim() || slugifyProcessId(title)
    if (!title.trim() && !id) {
      setError('Give the new process a name.')
      return
    }
    if (!id) {
      setFieldErrors({ process: 'process id is required' })
      setError('Give the new process a name.')
      return
    }

    const payload = buildPayload(id, title, tools)
    if (!runInlineValidation(payload)) {
      setError('Fix the highlighted fields before continuing.')
      return
    }

    try {
      const cfg = await createFromSchema.mutateAsync(payload)
      setProcess(cfg)
      setTools(toToolsValue(cfg))
      setStep(1)
    } catch (e) {
      if (e instanceof ProcessValidationError || (e instanceof Error && e.name === 'ProcessValidationError')) {
        const errs = e instanceof ProcessValidationError ? e.errors : []
        if (errs.length) setFieldErrors(fieldErrorMap(errs))
        setError(e.message)
      } else {
        setError(e instanceof Error ? e.message : 'Could not create the process.')
      }
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

  const pending = createFromSchema.isPending || updateProcess.isPending

  return (
    <>
      <PageHeader
        title="Connect a new agent"
        subtitle="Define the process config the gateway enforces, attach policy, then issue the agent its key"
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
                  onClick={() => {
                    setMode('new')
                    setTools(DEFAULT_TOOLS)
                  }}
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
                <>
                  <label className="flex flex-col gap-1.5 text-xs font-semibold text-text-secondary">
                    Process name
                    <Input
                      placeholder="Claims Review"
                      value={title}
                      onChange={(e) => onTitleChange(e.target.value)}
                    />
                  </label>
                  <label className="flex flex-col gap-1.5 text-xs font-semibold text-text-secondary">
                    Process id
                    <Input
                      placeholder="claims_review"
                      value={processId}
                      onChange={(e) => {
                        setProcessIdTouched(true)
                        setProcessId(e.target.value)
                      }}
                      className="font-mono"
                      aria-invalid={Boolean(fieldErrors.process)}
                    />
                    {fieldErrors.process && (
                      <span className="text-[11.5px] font-normal text-danger">{fieldErrors.process}</span>
                    )}
                    <span className="text-[11.5px] font-normal text-text-muted">
                      Writes configs/&lt;id&gt;.yaml the gateway enforces immediately — no code changes.
                    </span>
                  </label>
                  <ToolsEditor
                    value={tools}
                    onChange={(next) => {
                      setTools(next)
                      if (schema) {
                        const payload = buildPayload(
                          processId.trim() || slugifyProcessId(title) || 'process',
                          title,
                          next,
                        )
                        const errors = validateAgainstSchema(schema, payload)
                        setFieldErrors(fieldErrorMap(errors))
                      }
                    }}
                    evidenceDocOptions={evidenceOptions}
                    fieldErrors={fieldErrors}
                  />
                </>
              ) : (
                <div className="flex flex-col gap-4">
                  <div className="flex flex-col gap-2">
                    {processes.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => {
                          setExistingId(p.id)
                          setTools(toToolsValue(p))
                        }}
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
                  {existingId && (
                    <>
                      <div className="text-[13px] font-bold text-text-secondary">
                        Guardrails for{' '}
                        <span className="text-text-primary">
                          {processes.find((p) => p.id === existingId)?.title}
                        </span>
                      </div>
                      <ToolsEditor value={tools} onChange={setTools} />
                    </>
                  )}
                </div>
              )}

              <Button
                variant="accent"
                size="lg"
                className="self-end"
                onClick={handleStep0Next}
                disabled={pending}
              >
                {pending ? 'Saving…' : 'Next'}
              </Button>
            </Card>
          )}

          {step === 1 && process && (
            <div className="flex flex-col gap-4">
              <KnowledgeBaseEditor
                processId={process.id}
                processTitle={process.title}
                seedDocs={process.seed_docs}
                uploadedDocs={process.uploaded_docs}
              />
              <div className="flex justify-between">
                <Button variant="default" onClick={() => setStep(0)}>
                  Back
                </Button>
                <Button variant="accent" onClick={() => setStep(2)}>
                  Next
                </Button>
              </div>
            </div>
          )}

          {step === 2 && process && !created && (
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
                <Button variant="default" onClick={() => setStep(1)}>
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
