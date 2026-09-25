import { Plus, X } from 'lucide-react'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import type { ProcessToolInput } from '../../lib/api'

export interface ToolsValue {
  allowedTools: ProcessToolInput[]
  disallowedTools: string[]
  approvalThreshold: number
}

/** Controlled allow-list / disallow-list / threshold editor — shared between
 * the new-process wizard (local, unsaved state) and ConfigPage (state backed
 * by an existing process, saved via PUT /configs/:id). Neither owns how the
 * value gets persisted; that's the caller's job. */
export function ToolsEditor({
  value,
  onChange,
}: {
  value: ToolsValue
  onChange: (next: ToolsValue) => void
}) {
  function updateTool(index: number, patch: Partial<ProcessToolInput>) {
    const next = value.allowedTools.map((t, i) => (i === index ? { ...t, ...patch } : t))
    onChange({ ...value, allowedTools: next })
  }

  function addTool() {
    onChange({
      ...value,
      allowedTools: [...value.allowedTools, { name: '', max_auto_amount: null, unit: 'usd' }],
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

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
          Allow-listed tools
        </div>
        <div className="flex flex-col gap-2">
          {value.allowedTools.map((tool, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <Input
                placeholder="tool_name"
                value={tool.name}
                onChange={(e) => updateTool(i, { name: e.target.value })}
                className="min-w-[160px] flex-1 font-mono text-[12.5px]"
              />
              <Input
                type="number"
                placeholder="unlimited"
                value={tool.max_auto_amount ?? ''}
                onChange={(e) =>
                  updateTool(i, { max_auto_amount: e.target.value === '' ? null : Number(e.target.value) })
                }
                className="w-[130px] text-[12.5px]"
              />
              <Input
                placeholder="usd"
                value={tool.unit}
                onChange={(e) => updateTool(i, { unit: e.target.value })}
                className="w-[90px] text-[12.5px]"
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
      </label>

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
      </label>
    </div>
  )
}
