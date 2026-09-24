const STAGE_ORDER = ['retrieval', 'injection_flag', 'policy_check', 'tool_call', 'approval'] as const

function colorFor(stages: string[], decision: string | null, status: string, index: number): string {
  const stage = STAGE_ORDER[index]
  const reached = stages.includes(stage)
  if (!reached) {
    // Special-case: no injection flag raised is not a failure, just skip forward.
    if (stage === 'injection_flag' && stages.includes('policy_check')) return 'var(--color-success)'
    if (stage === 'approval' && status === 'completed' && decision === 'allow') return 'var(--color-success)'
    return 'var(--color-border)'
  }
  if (stage === 'injection_flag') return 'var(--color-warning)'
  if (stage === 'tool_call' && decision === 'block') return 'var(--color-danger)'
  if (stage === 'approval' && status === 'pending_approval') return 'var(--color-warning)'
  return 'var(--color-success)'
}

export function StageDots({
  stages,
  decision,
  status,
}: {
  stages: string[]
  decision: string | null
  status: string
}) {
  return (
    <div className="flex w-[170px] items-center gap-0.5">
      {STAGE_ORDER.map((stage, i) => {
        const color = colorFor(stages, decision, status, i)
        return (
          <span key={stage} className="flex flex-1 items-center gap-0.5 last:flex-none">
            <span className="h-[7px] w-[7px] shrink-0 rounded-full" style={{ background: color }} />
            {i < STAGE_ORDER.length - 1 && <span className="h-px flex-1" style={{ background: color }} />}
          </span>
        )
      })}
    </div>
  )
}
