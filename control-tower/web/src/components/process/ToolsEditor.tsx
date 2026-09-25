import { Plus, X } from 'lucide-react'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import type { ProcessToolInput } from '../../lib/api'
import { cn } from '../../lib/utils'

export interface ToolsValue {
  allowedTools: ProcessToolInput[]
  disallowedTools: string[]
  approvalThreshold: number
  requiredEvidenceDocs?: string[]
}

/** Controlled allow-list / disallow-list / threshold editor — shared between
 * the new-process wizard (local, unsaved state) and ConfigPage (state backed
 * by an existing process, saved via PUT /configs/:id). Neither owns how the
 * value gets persisted; that's the caller's job. */
export function ToolsEditor({
  value,
  onChange,
  evidenceDocOptions,
  fieldErrors,
}: {
  value: ToolsValue
  onChange: (next: ToolsValue) => void
  /** When set, shows a multi-select for required_evidence_docs (schema enum). */
  evidenceDocOptions?: string[]
  fieldErrors?: Record<string, string>
}) {
  function updateTool(index: number, patch: Partial<ProcessToolInput>) {
    const next = value.allowedTools.map((t, i) => (i === index ? { ...t, ...patch } : t))
    onChange({ ...value, allowedTools: next })
  }

  function addTool() {
    onChange({
      ...value,
      // No default unit — a tool call's amount isn't necessarily money (see
      // configs/risk_rating.yaml, which caps assign_risk_rating at "3 rating"
      // not "$3"). Forcing "usd" here silently mislabeled every non-currency
      // guardrail unless someone remembered to clear it.
      allowedTools: [...value.allowedTools, { name: '', max_auto_amount: null, unit: '' }],
    })
  }

  function removeTool(index: number) {
    onChange({ ...value, allowedTools: value.allowedTools.filter((_, i) => i !== index) })
  }

  function setDisallowed(text: string) {
    const list = text
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    onChange({ ...value, disallowedTools: list })
  }

  function toggleEvidence(doc: string) {
    const current = value.requiredEvidenceDocs ?? []
    const next = current.includes(doc) ? current.filter((d) => d !== doc) : [...current, doc]
    onChange({ ...value, requiredEvidenceDocs: next })
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
          Allow-listed tools
        </div>
        <div className="mb-2 text-[11.5px] leading-snug text-text-muted">
          Any tool call above its ceiling escalates for approval instead of running automatically — leave the
          ceiling blank for a tool with no natural amount (e.g. a lookup) or one that should always escalate.
          The unit is a label only ("usd", "rating", "count", …) — it's shown on the dashboard but never
          converted or enforced; the gateway just compares the raw number the agent sends.
        </div>
        {value.allowedTools.length > 0 && (
          <div className="mb-1.5 flex gap-2 px-0.5 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">
            <span className="min-w-[160px] flex-1">Tool name</span>
            <span className="w-[130px]">Auto-approve ceiling</span>
            <span className="w-[90px]">Unit</span>
            <span className="w-[15px]" />
          </div>
        )}
        <div className="flex flex-col gap-2">
          {value.allowedTools.map((tool, i) => (
            <div key={i} className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  placeholder="tool_name"
                  value={tool.name}
                  onChange={(e) => updateTool(i, { name: e.target.value })}
                  className="min-w-[160px] flex-1 font-mono text-[12.5px]"
                  aria-invalid={Boolean(fieldErrors?.[`allowed_tools.${i}.name`])}
                />
                <Input
                  type="number"
                  placeholder="no ceiling"
                  value={tool.max_auto_amount ?? ''}
                  onChange={(e) =>
                    updateTool(i, { max_auto_amount: e.target.value === '' ? null : Number(e.target.value) })
                  }
                  className="w-[130px] text-[12.5px]"
                />
                <Input
                  placeholder={tool.max_auto_amount == null ? 'n/a' : 'usd, rating…'}
                  value={tool.unit}
                  disabled={tool.max_auto_amount == null}
                  onChange={(e) => updateTool(i, { unit: e.target.value })}
                  title={tool.max_auto_amount == null ? 'No ceiling set — there is nothing for a unit to label' : undefined}
                  className="w-[90px] text-[12.5px] disabled:opacity-40"
                />
                <button
                  type="button"
                  onClick={() => removeTool(i)}
                  className="text-text-muted hover:text-danger"
                  aria-label={`Remove ${tool.name || 'tool'}`}
                >
                  <X size={15} strokeWidth={2} />
                </button>
              </div>
              {fieldErrors?.[`allowed_tools.${i}.name`] && (
                <div className="text-[11.5px] text-danger">{fieldErrors[`allowed_tools.${i}.name`]}</div>
              )}
            </div>
          ))}
          <Button type="button" variant="default" size="sm" className="self-start" onClick={addTool}>
            <Plus size={13} strokeWidth={2.2} />
            Add tool
          </Button>
        </div>
      </div>

      <label className="flex flex-col gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
        Disallowed tools (comma-separated)
        <Input
          placeholder="send_payment, modify_vendor_banking_details"
          defaultValue={value.disallowedTools.join(', ')}
          onBlur={(e) => setDisallowed(e.target.value)}
          className="font-mono text-[12.5px] normal-case tracking-normal"
        />
        {fieldErrors?.disallowed_tools && (
          <span className="normal-case tracking-normal text-danger">{fieldErrors.disallowed_tools}</span>
        )}
      </label>

      {evidenceDocOptions && evidenceDocOptions.length > 0 && (
        <fieldset className="flex flex-col gap-2">
          <legend className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            Required evidence docs
          </legend>
          <div className="flex flex-wrap gap-2">
            {evidenceDocOptions.map((doc) => {
              const checked = (value.requiredEvidenceDocs ?? []).includes(doc)
              return (
                <button
                  key={doc}
                  type="button"
                  onClick={() => toggleEvidence(doc)}
                  className={cn(
                    'rounded-md border px-2.5 py-1 font-mono text-[11.5px]',
                    checked
                      ? 'border-accent bg-accent-soft text-accent'
                      : 'border-border text-text-secondary hover:bg-surface-hover',
                  )}
                  aria-pressed={checked}
                >
                  {doc}
                </button>
              )
            })}
          </div>
          {fieldErrors?.required_evidence_docs && (
            <div className="text-[11.5px] text-danger">{fieldErrors.required_evidence_docs}</div>
          )}
          {Object.entries(fieldErrors ?? {})
            .filter(([k]) => k.startsWith('required_evidence_docs.'))
            .map(([k, msg]) => (
              <div key={k} className="text-[11.5px] text-danger">
                {msg}
              </div>
            ))}
        </fieldset>
      )}

      <label className="flex flex-col gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
        Approval threshold — escalate at risk_score ≥
        <Input
          type="number"
          min={0}
          max={100}
          value={value.approvalThreshold}
          onChange={(e) => onChange({ ...value, approvalThreshold: Number(e.target.value) })}
          className="w-[100px] font-mono text-[12.5px]"
        />
        {fieldErrors?.['approval_threshold.risk_score_gte'] && (
          <span className="normal-case tracking-normal text-danger">
            {fieldErrors['approval_threshold.risk_score_gte']}
          </span>
        )}
      </label>
    </div>
  )
}
