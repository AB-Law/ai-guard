// Mirrors control-tower/contracts/schemas.py and the api/main.py response shapes.
// Keep these in sync with the Python side by hand — there is no shared codegen yet.

export type GatewayDecisionLiteral = 'allow' | 'block' | 'escalate'

export type AuditEventType =
  | 'retrieval'
  | 'tool_call'
  | 'output_claim'
  | 'policy_check'
  | 'approval'
  | 'injection_flag'
  | 'incident'
  | 'rule_proposed'
  | 'rule_applied'

export interface GatewayDecision {
  call_id: string
  decision: GatewayDecisionLiteral
  reason: string
  policy_refs: string[]
  risk_score: number
  confidence_score: number
  evidence_score: number
}

export interface AuditLogEntry {
  entry_id: string
  process: string
  step_id: string
  event_type: AuditEventType
  payload: Record<string, unknown>
  scores: GatewayDecision | null
  timestamp: string
  prev_hash: string
  entry_hash: string
}

export type CaseStatus = 'running' | 'pending_approval' | 'completed' | string

export interface CaseRecord {
  case_id: string
  process: string
  status: CaseStatus
  call_id: string
  gateway_decision: GatewayDecision | null
  tool_result: Record<string, unknown> | null
  request: Record<string, unknown> | null
  source_app: string | null
  created_at: string
  origin?: string | null
}

export interface TrafficRow {
  case_id: string
  process: string
  status: CaseStatus
  decision: GatewayDecisionLiteral | null
  risk_score: number | null
  reason: string | null
  tool_name: string | null
  stages: string[]
  source_app: string | null
  created_at: string
}

export interface TrafficRecentResponse {
  cases: TrafficRow[]
  total_cases: number
  matched: number
  since_minutes: number | null
  limit: number
}

export interface CaseAuditResponse {
  case_id: string
  entries: AuditLogEntry[]
  chain_valid: boolean
}

export interface AuditVerifyResponse {
  valid: boolean
  entry_count: number
  first_invalid_entry_id: string | null
}

export interface AuditEntriesResponse {
  entries: AuditLogEntry[]
  total: number
  limit: number
  offset: number
}

export interface ProcessTool {
  name: string
  max_auto_amount: number | null
  unit: string
}

export type UploadedDocKind = 'uploaded' | 'custom'

export interface UploadedDoc {
  name: string
  kind: UploadedDocKind
  path: string
}

export interface ProcessConfig {
  id: string
  title: string
  config_path: string
  allowed_tools: ProcessTool[]
  disallowed_tools: string[]
  approval_threshold: { risk_score_gte: number }
  seed_docs: string[]
  uploaded_docs: UploadedDoc[]
}

export interface ConfigsResponse {
  processes: ProcessConfig[]
}

export type AppEnvironment = 'production' | 'staging'
export type AppStatus = 'connected' | 'revoked'
export type AppHealth = 'online' | 'stale' | 'offline' | 'never_seen'

export interface DeclaredMcpServer {
  name: string
  url?: string | null
  tools: string[]
}

export interface Application {
  app_id: string
  name: string
  environment: AppEnvironment
  process: string
  source_app: string
  status: AppStatus
  health: AppHealth | null
  key_display: string
  created_at: string
  revoked_at: string | null
  requests_today: number
  last_seen_at: string | null
  /** Alias of last_seen_at for older clients. */
  last_seen?: string | null
  owner?: string | null
  team?: string | null
  description?: string | null
  framework?: string | null
  runtime?: string | null
  tools?: string[]
  capabilities?: string[]
  mcp_servers?: DeclaredMcpServer[]
  /** Tool names seen in case traffic for this source_app — not MCP discovery. */
  observed_tools?: string[]
}

export interface ApplicationWithKey extends Application {
  api_key: string
}

export interface Approval {
  call_id: string
  case_id: string
  process: string
  origin?: string | null
  tool_name: string | null
  reason: string | null
  risk_score: number | null
  confidence_score: number | null
  evidence_score: number | null
  policy_refs: string[]
  source_app: string | null
  requested_at: string
  rule_id?: string | null
  rule_text?: string | null
  matched_span_preview?: string | null
  matched_span_hash?: string | null
  source_incident_id?: string | null
}
