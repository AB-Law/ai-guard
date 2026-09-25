import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button, buttonStyles } from '../components/ui/Button'
import { cn } from '../lib/utils'
import { useActiveProcess } from '../lib/processConfig'
import { useUpdateProcess } from '../lib/queries'
import { ToolsEditor, type ToolsValue } from '../components/process/ToolsEditor'
import { KnowledgeBaseEditor } from '../components/process/KnowledgeBaseEditor'

function toToolsValue(cfg: {
  allowed_tools: { name: string; max_auto_amount: number | null; unit: string }[]
  disallowed_tools: string[]
  approval_threshold: { risk_score_gte: number }
}): ToolsValue {
  return {
    allowedTools: cfg.allowed_tools.map((t) => ({ ...t })),
    disallowedTools: [...cfg.disallowed_tools],
    approvalThreshold: cfg.approval_threshold.risk_score_gte,
  }
}

export function ConfigPage() {
  const { active, processes, isLoading, setActiveId } = useActiveProcess()
  const updateProcess = useUpdateProcess()
  const [draft, setDraft] = useState<ToolsValue | null>(null)
  const [saveNote, setSaveNote] = useState<string | null>(null)

  // Keyed on id, not the whole object: a save triggers a configs refetch,
  // which gives `active` a new reference for the SAME process — that must
  // not wipe the just-set "Saved." note a moment later.
  useEffect(() => {
    if (active) setDraft(toToolsValue(active))
    setSaveNote(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id])

  const dirty =
    !!active &&
    !!draft &&
    JSON.stringify(draft) !== JSON.stringify(toToolsValue(active))

  function save() {
    if (!active || !draft) return
    updateProcess.mutate(
      {
        id: active.id,
        input: {
          allowed_tools: draft.allowedTools,
          disallowed_tools: draft.disallowedTools,
          approval_threshold: draft.approvalThreshold,
        },
      },
      { onSuccess: () => setSaveNote('Saved.'), onError: (e: Error) => setSaveNote(e.message) },
    )
  }

  return (
    <>
      <PageHeader
        title="Config & knowledge base"
        subtitle="Real process configs, parsed live from configs/*.yaml — the same file the gateway enforces against"
        showProcessSwitcher={false}
        actions={
          <Link to="/processes/new" className={buttonStyles({ variant: 'accent' })}>
            <Plus size={14} strokeWidth={2.2} />
            New process
          </Link>
        }
      />

      <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        <div className="mb-2.5 text-[13px] font-bold text-text-secondary">Active process</div>
        {isLoading && <div className="mb-[22px] text-sm text-text-muted">Loading configs…</div>}
        <div className="mb-[22px] grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {processes.map((p) => (
            <button
              key={p.id}
              onClick={() => setActiveId(p.id)}
              className={cn(
                'flex flex-col gap-2.5 rounded-xl border-[1.5px] px-5 py-[18px] text-left transition-colors',
                p.id === active?.id ? 'border-accent bg-accent-soft' : 'border-border bg-surface hover:bg-surface-hover',
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-[15px] font-bold">{p.title}</span>
                {p.id === active?.id && <Badge tone="success">Active</Badge>}
              </div>
              <span className="font-mono text-[11.5px] text-text-muted">{p.config_path}</span>
            </button>
          ))}
        </div>

        {active && draft && (
          <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
            <Card className="flex flex-col gap-3.5 px-5 py-[18px]">
              <div className="flex items-center justify-between">
                <div className="text-[13px] font-bold text-text-secondary">{active.title} — policy</div>
                {dirty && (
                  <Button variant="accent" size="sm" onClick={save} disabled={updateProcess.isPending}>
                    {updateProcess.isPending ? 'Saving…' : 'Save changes'}
                  </Button>
                )}
              </div>
              <ToolsEditor value={draft} onChange={setDraft} />
              {saveNote && <div className="text-xs text-text-secondary">{saveNote}</div>}
              <div className="text-[11.5px] leading-snug text-text-muted">
                Any tool not listed as allowed above is blocked by default — the gateway checks "is this on the
                allow-list", not "is this on the block-list" (least privilege, ARCHITECTURE.md §9).
              </div>
            </Card>

            <KnowledgeBaseEditor
              processId={active.id}
              processTitle={active.title}
              seedDocs={active.seed_docs}
              uploadedDocs={active.uploaded_docs}
            />
          </div>
        )}
      </div>
    </>
  )
}
