import { http, HttpResponse } from 'msw'
import {
  applications,
  approvals,
  auditEntries,
  caseAudit,
  cases,
  configs,
  createdApplication,
  traffic,
} from './data'

const api = (path: string) => `*/api${path}`

let appsState = [...applications]
let auditValid = true
let approvalsState = [...approvals]

export function resetMockState() {
  appsState = [...applications]
  auditValid = true
  approvalsState = [...approvals]
}

export const handlers = [
  http.get(api('/health'), () => HttpResponse.json({ status: 'ok' })),

  http.get(api('/cases'), () => HttpResponse.json({ cases })),

  http.get(api('/cases/:caseId'), ({ params }) => {
    const found = cases.find((c) => c.case_id === params.caseId)
    if (!found) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
    return HttpResponse.json(found)
  }),

  http.get(api('/cases/:caseId/audit'), ({ params }) =>
    HttpResponse.json(caseAudit(String(params.caseId))),
  ),

  http.post(api('/cases'), async ({ request }) => {
    const body = (await request.json()) as { case_id?: string; process?: string }
    return HttpResponse.json({
      ...cases[0],
      case_id: body.case_id ?? 'CASE-NEW',
      process: body.process ?? 'procurement_review',
    })
  }),

  http.get(api('/traffic/recent'), () => HttpResponse.json(traffic)),

  http.get(api('/approvals'), () =>
    HttpResponse.json({ approvals: approvalsState, count: approvalsState.length }),
  ),

  http.post(api('/approvals/:callId'), async ({ params, request }) => {
    const body = (await request.json()) as { action: string; actor: string }
    approvalsState = approvalsState.filter((a) => a.call_id !== params.callId)
    return HttpResponse.json({
      ...cases[1],
      status: body.action === 'approve' ? 'completed' : 'rejected',
      call_id: String(params.callId),
    })
  }),

  http.get(api('/configs'), () => HttpResponse.json(configs)),

  http.get(api('/audit/verify'), () =>
    HttpResponse.json({
      valid: auditValid,
      entry_count: auditEntries.length,
      first_invalid_entry_id: auditValid ? null : 'entry-3',
    }),
  ),

  http.get(api('/audit/entries'), () =>
    HttpResponse.json({
      entries: auditEntries,
      total: auditEntries.length,
      limit: 200,
      offset: 0,
    }),
  ),

  http.post(api('/audit/demo-tamper'), async ({ request }) => {
    const body = (await request.json()) as { enable: boolean }
    auditValid = !body.enable
    return HttpResponse.json({
      tampered: body.enable,
      entry_id: body.enable ? 'entry-3' : null,
    })
  }),

  http.get(api('/applications'), () =>
    HttpResponse.json({ applications: appsState }),
  ),

  http.post(api('/applications'), async ({ request }) => {
    const body = (await request.json()) as {
      name: string
      environment: 'production' | 'staging'
      process: string
    }
    const created = {
      ...createdApplication,
      name: body.name,
      environment: body.environment,
      process: body.process,
    }
    appsState = [created, ...appsState]
    return HttpResponse.json(created)
  }),

  http.post(api('/applications/:appId/revoke'), ({ params }) => {
    appsState = appsState.map((a) =>
      a.app_id === params.appId
        ? { ...a, status: 'revoked' as const, revoked_at: new Date().toISOString() }
        : a,
    )
    const found = appsState.find((a) => a.app_id === params.appId)
    return HttpResponse.json(found ?? applications[0])
  }),

  http.post(api('/demo/seed'), () =>
    HttpResponse.json({ ok: true, cases, pending_approval_count: approvalsState.length }),
  ),

  http.post(api('/demo/reset'), () => HttpResponse.json({ ok: true })),

  http.post(api('/investigate'), async ({ request }) => {
    const body = (await request.json()) as { question: string }
    return HttpResponse.json({
      answer: `Investigated: ${body.question}`,
      sources: ['entry-1'],
    })
  }),

  http.post(api('/knowledge/documents'), () =>
    HttpResponse.json({ ok: true, chunks: 3 }),
  ),
]
