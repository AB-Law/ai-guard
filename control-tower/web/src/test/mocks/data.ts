import type {
  Application,
  ApplicationWithKey,
  Approval,
  AuditLogEntry,
  CaseRecord,
  ConfigsResponse,
  TrafficRecentResponse,
} from '../../lib/types'

export const gatewayAllow = {
  call_id: 'call-allow-1',
  decision: 'allow' as const,
  reason: 'Within auto-approve threshold',
  policy_refs: ['policy:auto_approve'],
  risk_score: 22,
  confidence_score: 0.91,
  evidence_score: 0.88,
}

export const gatewayEscalate = {
  call_id: 'call-esc-1',
  decision: 'escalate' as const,
  reason: 'Amount exceeds auto-approve limit',
  policy_refs: ['policy:approval_threshold'],
  risk_score: 78,
  confidence_score: 0.7,
  evidence_score: 0.65,
}

export const gatewayBlock = {
  call_id: 'call-block-1',
  decision: 'block' as const,
  reason: 'Tool not on allow-list',
  policy_refs: ['policy:allow_list'],
  risk_score: 95,
  confidence_score: 0.95,
  evidence_score: 0.4,
}

export const cases: CaseRecord[] = [
  {
    case_id: 'CASE-ALLOW',
    process: 'procurement_review',
    status: 'completed',
    call_id: 'call-allow-1',
    gateway_decision: gatewayAllow,
    tool_result: { ok: true },
    request: { vendor_id: 'V-1001', amount: 2500 },
    source_app: 'claims-agent',
    created_at: new Date(Date.now() - 30_000).toISOString(),
  },
  {
    case_id: 'CASE-ESC',
    process: 'procurement_review',
    status: 'pending_approval',
    call_id: 'call-esc-1',
    gateway_decision: gatewayEscalate,
    tool_result: null,
    request: { vendor_id: 'V-1001', amount: 50000 },
    source_app: 'claims-agent',
    created_at: new Date(Date.now() - 120_000).toISOString(),
  },
  {
    case_id: 'CASE-BLOCK',
    process: 'onboarding_kyc',
    status: 'blocked',
    call_id: 'call-block-1',
    gateway_decision: gatewayBlock,
    tool_result: null,
    request: { customer_id: 'C-9' },
    source_app: null,
    created_at: new Date(Date.now() - 3600_000).toISOString(),
  },
]

export const traffic: TrafficRecentResponse = {
  cases: [
    {
      case_id: 'CASE-ALLOW',
      process: 'procurement_review',
      status: 'completed',
      decision: 'allow',
      risk_score: 22,
      reason: gatewayAllow.reason,
      tool_name: 'create_purchase_order',
      stages: ['retrieval', 'policy_check', 'tool_call'],
      source_app: 'claims-agent',
      created_at: cases[0].created_at,
    },
    {
      case_id: 'CASE-ESC',
      process: 'procurement_review',
      status: 'pending_approval',
      decision: 'escalate',
      risk_score: 78,
      reason: gatewayEscalate.reason,
      tool_name: 'create_purchase_order',
      stages: ['retrieval', 'injection_flag', 'policy_check', 'approval'],
      source_app: 'claims-agent',
      created_at: cases[1].created_at,
    },
    {
      case_id: 'CASE-BLOCK',
      process: 'onboarding_kyc',
      status: 'blocked',
      decision: 'block',
      risk_score: 95,
      reason: gatewayBlock.reason,
      tool_name: 'send_payment',
      stages: ['retrieval', 'policy_check', 'tool_call'],
      source_app: null,
      created_at: cases[2].created_at,
    },
  ],
  total_cases: 3,
  matched: 3,
  since_minutes: null,
  limit: 50,
}

export const approvals: Approval[] = [
  {
    call_id: 'call-esc-1',
    case_id: 'CASE-ESC',
    process: 'procurement_review',
    tool_name: 'create_purchase_order',
    reason: gatewayEscalate.reason,
    risk_score: 78,
    confidence_score: 0.7,
    evidence_score: 0.65,
    policy_refs: gatewayEscalate.policy_refs,
    source_app: 'claims-agent',
    requested_at: cases[1].created_at,
  },
]

export const auditEntries: AuditLogEntry[] = [
  {
    entry_id: 'entry-1',
    process: 'procurement_review',
    step_id: 'retrieve',
    event_type: 'retrieval',
    payload: { case_id: 'CASE-ALLOW', chunks: 2 },
    scores: null,
    timestamp: new Date(Date.now() - 90_000).toISOString(),
    prev_hash: '0'.repeat(64),
    entry_hash: 'a'.repeat(64),
  },
  {
    entry_id: 'entry-2',
    process: 'procurement_review',
    step_id: 'scan',
    event_type: 'injection_flag',
    payload: { case_id: 'CASE-ESC', snippet: 'Ignore previous instructions' },
    scores: null,
    timestamp: new Date(Date.now() - 80_000).toISOString(),
    prev_hash: 'a'.repeat(64),
    entry_hash: 'b'.repeat(64),
  },
  {
    entry_id: 'entry-3',
    process: 'procurement_review',
    step_id: 'gateway',
    event_type: 'policy_check',
    payload: { case_id: 'CASE-ESC' },
    scores: gatewayEscalate,
    timestamp: new Date(Date.now() - 70_000).toISOString(),
    prev_hash: 'b'.repeat(64),
    entry_hash: 'c'.repeat(64),
  },
  {
    entry_id: 'entry-4',
    process: 'onboarding_kyc',
    step_id: 'tool',
    event_type: 'tool_call',
    payload: { case_id: 'CASE-BLOCK', tool_name: 'send_payment' },
    scores: gatewayBlock,
    timestamp: new Date(Date.now() - 60_000).toISOString(),
    prev_hash: 'c'.repeat(64),
    entry_hash: 'd'.repeat(64),
  },
  {
    entry_id: 'entry-5',
    process: 'procurement_review',
    step_id: 'approve',
    event_type: 'approval',
    payload: { case_id: 'CASE-ESC', action: 'approve', actor: 'demo@aegis.dev' },
    scores: null,
    timestamp: new Date(Date.now() - 50_000).toISOString(),
    prev_hash: 'd'.repeat(64),
    entry_hash: 'e'.repeat(64),
  },
  {
    entry_id: 'entry-6',
    process: 'procurement_review',
    step_id: 'claim',
    event_type: 'output_claim',
    payload: { case_id: 'CASE-ALLOW', claim: 'Vendor is active' },
    scores: null,
    timestamp: new Date(Date.now() - 40_000).toISOString(),
    prev_hash: 'e'.repeat(64),
    entry_hash: 'f'.repeat(64),
  },
]

export const configs: ConfigsResponse = {
  processes: [
    {
      id: 'procurement_review',
      title: 'Procurement Review',
      config_path: 'configs/procurement_review.yaml',
      allowed_tools: [
        { name: 'create_purchase_order', max_auto_amount: 10000, unit: 'usd' },
        { name: 'lookup_vendor', max_auto_amount: null, unit: 'usd' },
      ],
      disallowed_tools: ['send_payment'],
      approval_threshold: { risk_score_gte: 60 },
      seed_docs: ['policies/procurement.md'],
      uploaded_docs: [
        { name: 'extra-policy.md', kind: 'uploaded', path: 'extra-policy.md' },
        { name: 'custom-note.md', kind: 'custom', path: 'custom/custom-note.md' },
      ],
    },
    {
      id: 'onboarding_kyc',
      title: 'Onboarding KYC',
      config_path: 'configs/onboarding_kyc.yaml',
      allowed_tools: [{ name: 'verify_identity', max_auto_amount: 5, unit: 'checks' }],
      disallowed_tools: ['wire_funds'],
      approval_threshold: { risk_score_gte: 50 },
      seed_docs: [],
      uploaded_docs: [],
    },
  ],
}

export const applications: Application[] = [
  {
    app_id: 'app-1',
    name: 'Claims Review Agent',
    environment: 'production',
    process: 'procurement_review',
    source_app: 'claims-agent',
    status: 'connected',
    key_display: 'aeg_••••abcd',
    created_at: new Date(Date.now() - 86400_000).toISOString(),
    revoked_at: null,
    requests_today: 12,
    last_seen: new Date(Date.now() - 600_000).toISOString(),
  },
  {
    app_id: 'app-2',
    name: 'Staging Bot',
    environment: 'staging',
    process: 'onboarding_kyc',
    source_app: 'staging-bot',
    status: 'revoked',
    key_display: 'aeg_••••zzzz',
    created_at: new Date(Date.now() - 172800_000).toISOString(),
    revoked_at: new Date(Date.now() - 3600_000).toISOString(),
    requests_today: 0,
    last_seen: null,
  },
]

export const createdApplication: ApplicationWithKey = {
  ...applications[0],
  app_id: 'app-new',
  name: 'New Agent',
  api_key: 'aeg_live_secret_key_only_once',
  source_app: 'new-agent',
  key_display: 'aeg_••••once',
  status: 'connected',
  revoked_at: null,
  requests_today: 0,
  last_seen: null,
}

export function caseAudit(caseId: string) {
  return {
    case_id: caseId,
    entries: auditEntries.filter((e) => (e.payload as { case_id?: string }).case_id === caseId),
    chain_valid: true,
  }
}
