// HTTP client for the Aegis FastAPI control tower — TS mirror of dashboard/api_client.py.
// Requests go through Vite's /api proxy (see vite.config.ts) so the browser never needs CORS.

import type {
  ApplicationWithKey,
  AppEnvironment,
  Application,
  Approval,
  AuditEntriesResponse,
  AuditVerifyResponse,
  CaseAuditResponse,
  CaseRecord,
  ConfigsResponse,
  ProcessConfig,
  TrafficRecentResponse,
  OpsMetricsSnapshot,
} from './types'

const BASE = '/api'
const TOKEN_KEY = 'aegis.auth.token'

// Read fresh from storage on every call rather than caching in a module
// variable — AuthProvider writes here directly on login/logout and this
// module has no way to know when that happens otherwise.
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // localStorage unavailable — session just won't survive a refresh.
  }
}

/** Dispatched when a request 401s so AuthProvider can drop the stale session
 * and bounce to /login, without api.ts importing React/router. */
export const UNAUTHORIZED_EVENT = 'aegis:unauthorized'

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    ...init,
  })
  if (res.status === 401) {
    setToken(null)
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status} ${detail}`)
  }
  return res.json() as Promise<T>
}

export function login(password: string): Promise<{ access_token: string; token_type: string }> {
  return request('/auth/login', { method: 'POST', body: JSON.stringify({ password }) })
}

export function health(): Promise<{ status: string }> {
  return request('/health')
}

export async function listCases(): Promise<CaseRecord[]> {
  const body = await request<{ cases: CaseRecord[] }>('/cases')
  return body.cases ?? []
}

export function getCase(caseId: string): Promise<CaseRecord> {
  return request(`/cases/${encodeURIComponent(caseId)}`)
}

export function getCaseAudit(caseId: string): Promise<CaseAuditResponse> {
  return request(`/cases/${encodeURIComponent(caseId)}/audit`)
}

export function verifyAudit(): Promise<AuditVerifyResponse> {
  return request('/audit/verify')
}

export interface SubmitCaseInput {
  process: string
  request: Record<string, unknown>
  mock_agent_plan?: Record<string, unknown>
  force_chunk_ids?: string[]
  case_id?: string
  source_app?: string
}

export function submitCase(input: SubmitCaseInput): Promise<CaseRecord> {
  return request('/cases', { method: 'POST', body: JSON.stringify(input) })
}

export function seedDemo(): Promise<{ ok: boolean; cases: CaseRecord[]; pending_approval_count: number }> {
  return request('/demo/seed', { method: 'POST' })
}

export function resetDemo(): Promise<{ ok: boolean }> {
  return request('/demo/reset', { method: 'POST' })
}

export function investigate(
  question: string,
  opts?: { case_id?: string; mock_answer?: Record<string, unknown> },
): Promise<{ answer: string; sources?: string[] }> {
  return request('/investigate', {
    method: 'POST',
    body: JSON.stringify({ question, ...opts }),
  })
}

export interface TrafficRecentParams {
  limit?: number
  since_minutes?: number
  source_app?: string
  decision?: string
}

export function trafficRecent(params: TrafficRecentParams = {}): Promise<TrafficRecentResponse> {
  const search = new URLSearchParams()
  search.set('limit', String(params.limit ?? 100))
  if (params.since_minutes != null) search.set('since_minutes', String(params.since_minutes))
  if (params.source_app) search.set('source_app', params.source_app)
  if (params.decision) search.set('decision', params.decision)
  return request(`/traffic/recent?${search.toString()}`)
}

export async function listApprovals(): Promise<Approval[]> {
  const body = await request<{ approvals: Approval[]; count: number }>('/approvals')
  return body.approvals ?? []
}

export function approve(
  callId: string,
  action: 'approve' | 'reject',
  actor: string,
  ruleText?: string | null,
): Promise<CaseRecord> {
  const body: Record<string, string> = { action, actor }
  if (ruleText != null && ruleText !== '') body.rule_text = ruleText
  return request(`/approvals/${encodeURIComponent(callId)}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function listConfigs(): Promise<ConfigsResponse> {
  return request('/configs')
}

export interface ProcessToolInput {
  name: string
  max_auto_amount: number | null
  unit: string
}

export interface CreateProcessInput {
  title: string
  allowed_tools?: ProcessToolInput[]
  disallowed_tools?: string[]
  approval_threshold?: number
}

/** Full ProcessConfig payload for POST /processes (schema-driven wizard). */
export interface ProcessConfigPayload {
  process: string
  title?: string | null
  allowed_tools: ProcessToolInput[]
  disallowed_tools: string[]
  required_evidence_docs: string[]
  approval_threshold: { risk_score_gte: number }
  knowledge_base_paths: string[]
}

export interface FieldError {
  loc: (string | number)[]
  msg: string
  type: string
}

export class ProcessValidationError extends Error {
  readonly errors: FieldError[]
  constructor(errors: FieldError[], status = 422) {
    super(errors[0]?.msg ?? `POST /processes failed: ${status}`)
    this.name = 'ProcessValidationError'
    this.errors = errors
    Object.setPrototypeOf(this, new.target.prototype)
  }
}

export function getProcessSchema(): Promise<Record<string, unknown>> {
  return request('/processes/schema')
}

export async function createProcessFromSchema(input: ProcessConfigPayload): Promise<ProcessConfig> {
  const res = await fetch(`${BASE}/processes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(input),
  })
  if (res.status === 401) {
    setToken(null)
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  if (!res.ok) {
    let parsed: { detail?: FieldError[] } | null = null
    const text = await res.text().catch(() => '')
    try {
      parsed = JSON.parse(text) as { detail?: FieldError[] }
    } catch {
      parsed = null
    }
    if (res.status === 422 && Array.isArray(parsed?.detail)) {
      throw new ProcessValidationError(parsed.detail, 422)
    }
    throw new Error(`POST /processes failed: ${res.status} ${text}`)
  }
  return res.json() as Promise<ProcessConfig>
}

export function createProcess(input: CreateProcessInput): Promise<ProcessConfig> {
  return request('/configs', { method: 'POST', body: JSON.stringify(input) })
}

export interface UpdateProcessInput {
  allowed_tools?: ProcessToolInput[]
  disallowed_tools?: string[]
  approval_threshold?: number
}

export function updateProcess(id: string, input: UpdateProcessInput): Promise<{ id: string }> {
  return request(`/configs/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(input) })
}

export interface CreatePolicyInput {
  process: string
  title: string
  content: string
}

export function createPolicy(
  input: CreatePolicyInput,
): Promise<{ ok: boolean; name: string; path: string; chunks_added: number; kb_size: number }> {
  return request('/knowledge/policies', { method: 'POST', body: JSON.stringify(input) })
}

export function getPolicy(process: string, filename: string): Promise<{ name: string; content: string }> {
  return request(`/knowledge/policies/${encodeURIComponent(process)}/${encodeURIComponent(filename)}`)
}

export function updatePolicy(
  process: string,
  filename: string,
  input: { title: string; content: string },
): Promise<{ ok: boolean; name: string; chunks_added: number; kb_size: number }> {
  return request(`/knowledge/policies/${encodeURIComponent(process)}/${encodeURIComponent(filename)}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

export function deleteDocument(
  process: string,
  docPath: string,
): Promise<{ ok: boolean; removed_chunks: number; kb_size: number }> {
  const encodedPath = docPath.split('/').map(encodeURIComponent).join('/')
  return request(`/knowledge/documents/${encodeURIComponent(process)}/${encodedPath}`, { method: 'DELETE' })
}

export interface AuditEntriesParams {
  limit?: number
  offset?: number
  process?: string
  event_type?: string
  decision?: string
}

export function auditEntries(params: AuditEntriesParams = {}): Promise<AuditEntriesResponse> {
  const search = new URLSearchParams()
  search.set('limit', String(params.limit ?? 200))
  search.set('offset', String(params.offset ?? 0))
  if (params.process) search.set('process', params.process)
  if (params.event_type) search.set('event_type', params.event_type)
  if (params.decision) search.set('decision', params.decision)
  return request(`/audit/entries?${search.toString()}`)
}

export function demoTamper(enable: boolean): Promise<{ tampered: boolean; entry_id: string | null }> {
  return request('/audit/demo-tamper', { method: 'POST', body: JSON.stringify({ enable }) })
}

export async function listApplications(): Promise<Application[]> {
  const body = await request<{ applications: Application[] }>('/applications')
  return body.applications ?? []
}

export interface CreateApplicationInput {
  name: string
  environment: AppEnvironment
  process: string
  source_app?: string
  owner?: string
  team?: string
  description?: string
  framework?: string
  runtime?: string
  tools?: string[]
  capabilities?: string[]
  mcp_servers?: { name: string; url?: string | null; tools?: string[] }[]
}

export function createApplication(input: CreateApplicationInput): Promise<ApplicationWithKey> {
  return request('/applications', { method: 'POST', body: JSON.stringify(input) })
}

export type UpdateApplicationInventoryInput = Partial<
  Pick<
    Application,
    | 'owner'
    | 'team'
    | 'description'
    | 'framework'
    | 'runtime'
    | 'tools'
    | 'capabilities'
    | 'mcp_servers'
  >
>

export function updateApplicationInventory(
  appId: string,
  input: UpdateApplicationInventoryInput,
): Promise<Application> {
  return request(`/applications/${encodeURIComponent(appId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function revokeApplication(appId: string): Promise<Application> {
  return request(`/applications/${encodeURIComponent(appId)}/revoke`, { method: 'POST' })
}

export async function uploadDocument(file: File, process: string): Promise<{ ok: boolean; chunks?: number }> {
  const form = new FormData()
  form.append('file', file)
  form.append('process', process)
  const res = await fetch(`${BASE}/knowledge/documents`, { method: 'POST', body: form, headers: authHeaders() })
  if (res.status === 401) {
    setToken(null)
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`upload failed: ${res.status} ${detail}`)
  }
  return res.json()
}

export function opsMetrics(): Promise<OpsMetricsSnapshot> {
  return request('/ops/metrics')
}
