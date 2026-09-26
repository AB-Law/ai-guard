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
let configsState = { processes: configs.processes.map((p) => ({ ...p, uploaded_docs: [...p.uploaded_docs] })) }
const policyContent = new Map<string, string>([['procurement_review/custom/custom-note.md', 'Original custom note body.']])

export function resetMockState() {
  appsState = [...applications]
  auditValid = true
  approvalsState = [...approvals]
  configsState = { processes: configs.processes.map((p) => ({ ...p, uploaded_docs: [...p.uploaded_docs] })) }
  policyContent.clear()
  policyContent.set('procurement_review/custom/custom-note.md', 'Original custom note body.')
}

export const handlers = [
  http.post(api('/auth/login'), async ({ request }) => {
    const body = (await request.json()) as { password: string }
    if (!body.password || body.password === 'wrong') {
      return HttpResponse.json({ detail: 'invalid password' }, { status: 401 })
    }
    return HttpResponse.json({ access_token: 'test-token', token_type: 'bearer' })
  }),

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

  http.get(api('/configs'), () => HttpResponse.json(configsState)),

  http.get(api('/processes/schema'), () =>
    HttpResponse.json({
      title: 'ProcessConfig',
      type: 'object',
      required: [
        'process',
        'allowed_tools',
        'disallowed_tools',
        'required_evidence_docs',
        'approval_threshold',
        'knowledge_base_paths',
      ],
      properties: {
        process: { type: 'string' },
        title: { type: ['string', 'null'] },
        allowed_tools: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              name: { type: 'string' },
              max_auto_amount: { type: ['number', 'null'] },
              unit: { type: 'string' },
            },
            required: ['name'],
          },
        },
        disallowed_tools: { type: 'array', items: { type: 'string' } },
        required_evidence_docs: {
          type: 'array',
          items: {
            type: 'string',
            enum: [
              'finance_policy',
              'kyc_policy',
              'procurement_policy',
              'rag_bot_policy',
              'risk_rating_policy',
              'vendor_master_list',
            ],
          },
        },
        approval_threshold: {
          type: 'object',
          properties: { risk_score_gte: { type: 'integer', minimum: 0, maximum: 100 } },
          required: ['risk_score_gte'],
        },
        knowledge_base_paths: { type: 'array', items: { type: 'string' } },
      },
      'x-known-tools': ['create_purchase_order', 'approve_claim', 'submit_expense_report'],
    }),
  ),

  http.post(api('/processes'), async ({ request }) => {
    const body = (await request.json()) as {
      process: string
      title?: string | null
      allowed_tools?: unknown[]
      disallowed_tools?: string[]
      required_evidence_docs?: string[]
      approval_threshold?: { risk_score_gte: number }
      knowledge_base_paths?: string[]
    }
    if (!body.process || !/^[a-z][a-z0-9_]*$/.test(body.process)) {
      return HttpResponse.json(
        {
          detail: [
            {
              loc: ['process'],
              msg: 'process id must start with a lowercase letter',
              type: 'invalid_process_id',
            },
          ],
        },
        { status: 422 },
      )
    }
    const created = {
      id: body.process,
      title: body.title || body.process.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      config_path: `configs/${body.process}.yaml`,
      allowed_tools: (body.allowed_tools as typeof configsState.processes[0]['allowed_tools']) ?? [],
      disallowed_tools: body.disallowed_tools ?? [],
      approval_threshold: body.approval_threshold ?? { risk_score_gte: 60 },
      seed_docs: [],
      uploaded_docs: [],
    }
    configsState = { processes: [...configsState.processes, created] }
    return HttpResponse.json(created)
  }),

  http.post(api('/configs'), async ({ request }) => {
    const body = (await request.json()) as { title: string; approval_threshold?: number }
    const id = body.title.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
    const created = {
      id,
      title: body.title,
      config_path: `configs/${id}.yaml`,
      allowed_tools: [],
      disallowed_tools: [],
      approval_threshold: { risk_score_gte: body.approval_threshold ?? 60 },
      seed_docs: [],
      uploaded_docs: [],
    }
    configsState = { processes: [...configsState.processes, created] }
    return HttpResponse.json(created)
  }),

  http.put(api('/configs/:id'), async ({ params, request }) => {
    const body = (await request.json()) as {
      allowed_tools?: unknown[]
      disallowed_tools?: string[]
      approval_threshold?: number
    }
    configsState = {
      processes: configsState.processes.map((p) =>
        p.id === params.id
          ? {
              ...p,
              allowed_tools: (body.allowed_tools as typeof p.allowed_tools) ?? p.allowed_tools,
              disallowed_tools: body.disallowed_tools ?? p.disallowed_tools,
              approval_threshold:
                body.approval_threshold != null
                  ? { risk_score_gte: body.approval_threshold }
                  : p.approval_threshold,
            }
          : p,
      ),
    }
    return HttpResponse.json({ id: params.id })
  }),

  http.post(api('/knowledge/policies'), async ({ request }) => {
    const body = (await request.json()) as { process: string; title: string; content: string }
    const filename = `${body.title.toLowerCase().replace(/[^a-z0-9]+/g, '_')}.md`
    policyContent.set(`${body.process}/custom/${filename}`, body.content)
    configsState = {
      processes: configsState.processes.map((p) =>
        p.id === body.process
          ? { ...p, uploaded_docs: [...p.uploaded_docs, { name: filename, kind: 'custom' as const, path: `custom/${filename}` }] }
          : p,
      ),
    }
    return HttpResponse.json({ ok: true, name: filename, path: `custom/${filename}`, chunks_added: 1, kb_size: 1 })
  }),

  http.get(api('/knowledge/policies/:process/:filename'), ({ params }) => {
    const key = `${params.process}/custom/${params.filename}`
    const content = policyContent.get(key)
    if (content == null) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
    return HttpResponse.json({ name: params.filename, content })
  }),

  http.put(api('/knowledge/policies/:process/:filename'), async ({ params, request }) => {
    const body = (await request.json()) as { content: string }
    const key = `${params.process}/custom/${params.filename}`
    if (!policyContent.has(key)) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
    policyContent.set(key, body.content)
    return HttpResponse.json({ ok: true, name: params.filename, chunks_added: 1, kb_size: 1 })
  }),

  http.delete(api('/knowledge/documents/:process/:docPath*'), ({ params }) => {
    const segments = Array.isArray(params.docPath) ? params.docPath : [params.docPath as string]
    const docPath = segments.join('/')
    policyContent.delete(`${params.process}/${docPath}`)
    configsState = {
      processes: configsState.processes.map((p) =>
        p.id === params.process ? { ...p, uploaded_docs: p.uploaded_docs.filter((d) => d.path !== docPath) } : p,
      ),
    }
    return HttpResponse.json({ ok: true, removed_chunks: 1, kb_size: 0 })
  }),

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
      source_app?: string
    }
    const created = {
      ...createdApplication,
      name: body.name,
      environment: body.environment,
      process: body.process,
      source_app: body.source_app ?? createdApplication.source_app,
      health: 'never_seen' as const,
      last_seen_at: null,
      last_seen: null,
    }
    appsState = [created, ...appsState]
    return HttpResponse.json(created)
  }),

  http.patch(api('/applications/:appId'), async ({ params, request }) => {
    const body = (await request.json()) as Record<string, unknown>
    appsState = appsState.map((a) =>
      a.app_id === params.appId
        ? {
            ...a,
            ...body,
            // Never leak key material on update responses.
            api_key: undefined,
          }
        : a,
    ) as typeof appsState
    const found = appsState.find((a) => a.app_id === params.appId)
    return HttpResponse.json(found ?? applications[0])
  }),

  http.post(api('/applications/heartbeat'), () => {
    const now = new Date().toISOString()
    const target = appsState.find((a) => a.status === 'connected') ?? appsState[0]
    if (!target) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
    const updated = { ...target, last_seen_at: now, last_seen: now, health: 'online' as const }
    appsState = appsState.map((a) => (a.app_id === updated.app_id ? updated : a))
    return HttpResponse.json(updated)
  }),

  http.post(api('/applications/:appId/revoke'), ({ params }) => {
    appsState = appsState.map((a) =>
      a.app_id === params.appId
        ? {
            ...a,
            status: 'revoked' as const,
            health: null,
            revoked_at: new Date().toISOString(),
          }
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
