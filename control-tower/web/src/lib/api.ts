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
  TrafficRecentResponse,
} from './types'

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status} ${detail}`)
  }
  return res.json() as Promise<T>
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

export function approve(callId: string, action: 'approve' | 'reject', actor: string): Promise<CaseRecord> {
  return request(`/approvals/${encodeURIComponent(callId)}`, {
    method: 'POST',
    body: JSON.stringify({ action, actor }),
  })
}

export function listConfigs(): Promise<ConfigsResponse> {
  return request('/configs')
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
}

export function createApplication(input: CreateApplicationInput): Promise<ApplicationWithKey> {
  return request('/applications', { method: 'POST', body: JSON.stringify(input) })
}

export function revokeApplication(appId: string): Promise<Application> {
  return request(`/applications/${encodeURIComponent(appId)}/revoke`, { method: 'POST' })
}

export async function uploadDocument(file: File, process: string): Promise<{ ok: boolean; chunks?: number }> {
  const form = new FormData()
  form.append('file', file)
  form.append('process', process)
  const res = await fetch(`${BASE}/knowledge/documents`, { method: 'POST', body: form })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`upload failed: ${res.status} ${detail}`)
  }
  return res.json()
}
