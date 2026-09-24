import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Upload } from 'lucide-react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { cn } from '../lib/utils'
import { useActiveProcess } from '../lib/processConfig'
import * as api from '../lib/api'
import type { ProcessTool } from '../lib/types'

function formatLimit(t: ProcessTool): string {
  if (t.max_auto_amount == null) return 'max auto: unlimited'
  if (t.unit === 'usd') return `max auto: $${t.max_auto_amount.toLocaleString()}`
  return `max auto: ${t.max_auto_amount.toLocaleString()} ${t.unit}`
}

export function ConfigPage() {
  const { active, processes, isLoading, setActiveId } = useActiveProcess()
  const fileInput = useRef<HTMLInputElement>(null)
  const [uploadNote, setUploadNote] = useState<string | null>(null)

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(file, active?.id ?? ''),
    onSuccess: (_res, file) => setUploadNote(`${file.name} indexed into ${active?.title}`),
    onError: (err: Error) => setUploadNote(err.message),
  })

  function handleFiles(files: FileList | null) {
    const file = files?.[0]
    if (file && active) upload.mutate(file)
  }

  return (
    <>
      <PageHeader
        title="Config & knowledge base"
        subtitle="Real process configs, parsed live from configs/*.yaml — the same file the gateway enforces against"
        showProcessSwitcher={false}
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

        {active && (
          <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
            <Card className="flex flex-col gap-3.5 px-5 py-[18px]">
              <div className="text-[13px] font-bold text-text-secondary">{active.title} — allow-listed tools</div>
              <div className="flex flex-col gap-1.5">
                {active.allowed_tools.map((t) => (
                  <div key={t.name} className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-2.5 text-[12.5px]">
                    <span className="font-mono">{t.name}</span>
                    <span className="text-text-muted">{formatLimit(t)}</span>
                  </div>
                ))}
              </div>
              <div className="mt-1 text-xs font-bold text-danger">Disallowed</div>
              <div className="flex flex-wrap gap-1.5">
                {active.disallowed_tools.map((d) => (
                  <span key={d} className="rounded-md bg-danger-soft px-2.5 py-1 font-mono text-[11.5px] text-danger">
                    {d}
                  </span>
                ))}
              </div>
              <div className="text-[11.5px] leading-snug text-text-muted">
                Any tool not listed as allowed above is blocked by default — the gateway checks "is this on the
                allow-list", not "is this on the block-list" (least privilege, ARCHITECTURE.md §9).
              </div>
              <div className="mt-1 flex justify-between border-t border-border pt-3 text-[12.5px]">
                <span className="text-text-muted">Approval threshold</span>
                <span className="font-mono font-bold">risk_score ≥ {active.approval_threshold.risk_score_gte}</span>
              </div>
            </Card>

            <Card className="flex flex-col gap-3.5 px-5 py-[18px]">
              <div className="text-[13px] font-bold text-text-secondary">Knowledge base — {active.title}</div>
              <button
                onClick={() => fileInput.current?.click()}
                className="flex flex-col items-center gap-2 rounded-xl border-[1.5px] border-dashed border-border px-6 py-[26px] text-text-secondary hover:border-accent hover:text-text-primary"
              >
                <Upload size={22} strokeWidth={1.6} />
                <span className="text-[12.5px] font-semibold">
                  {upload.isPending ? 'Uploading…' : 'Drop a .md / .txt / .csv policy document'}
                </span>
                <span className="text-[11.5px] text-text-muted">Indexed into the live KB immediately — no restart</span>
              </button>
              <input
                ref={fileInput}
                type="file"
                accept=".md,.txt,.csv"
                className="hidden"
                onChange={(e) => handleFiles(e.target.files)}
              />
              {uploadNote && <div className="text-xs text-text-secondary">{uploadNote}</div>}
              <div className="flex flex-col gap-1.5">
                {active.seed_docs.map((doc) => (
                  <div key={doc} className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-2.5 text-[12.5px]">
                    <span className="font-mono">{doc}</span>
                    <span className="text-text-muted">seed</span>
                  </div>
                ))}
                {active.uploaded_docs.map((doc) => (
                  <div key={doc} className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-2.5 text-[12.5px]">
                    <span className="font-mono">{doc}</span>
                    <span className="text-success">uploaded</span>
                  </div>
                ))}
                {active.seed_docs.length === 0 && active.uploaded_docs.length === 0 && (
                  <div className="text-xs text-text-muted">No documents indexed yet.</div>
                )}
              </div>
            </Card>
          </div>
        )}
      </div>
    </>
  )
}
