import { describe, expect, it, vi } from 'vitest'
import * as api from './api'
import { server } from '../test/mocks/server'
import { http, HttpResponse } from 'msw'

describe('api client', () => {
  it('health', async () => {
    await expect(api.health()).resolves.toEqual({ status: 'ok' })
  })

  it('listCases / getCase / getCaseAudit', async () => {
    const list = await api.listCases()
    expect(list.length).toBeGreaterThan(0)
    const one = await api.getCase('CASE-ALLOW')
    expect(one.case_id).toBe('CASE-ALLOW')
    const audit = await api.getCaseAudit('CASE-ALLOW')
    expect(audit.chain_valid).toBe(true)
  })

  it('submitCase / seedDemo / resetDemo / investigate', async () => {
    const submitted = await api.submitCase({
      process: 'procurement_review',
      request: { amount: 1 },
      case_id: 'CASE-X',
    })
    expect(submitted.case_id).toBe('CASE-X')
    await expect(api.seedDemo()).resolves.toMatchObject({ ok: true })
    await expect(api.resetDemo()).resolves.toEqual({ ok: true })
    await expect(api.investigate('why blocked?')).resolves.toMatchObject({
      answer: expect.stringContaining('why blocked?'),
    })
  })

  it('trafficRecent with params', async () => {
    const res = await api.trafficRecent({
      limit: 10,
      since_minutes: 60,
      source_app: 'claims-agent',
      decision: 'allow',
    })
    expect(res.total_cases).toBe(3)
  })

  it('approvals approve/reject', async () => {
    const list = await api.listApprovals()
    expect(list[0].call_id).toBe('call-esc-1')
    const approved = await api.approve('call-esc-1', 'approve', 'tester@aegis.dev')
    expect(approved.status).toBe('completed')
  })

  it('configs / audit / applications', async () => {
    const cfg = await api.listConfigs()
    expect(cfg.processes).toHaveLength(2)

    const verify = await api.verifyAudit()
    expect(verify.valid).toBe(true)

    const entries = await api.auditEntries({
      limit: 50,
      offset: 0,
      process: 'procurement_review',
      event_type: 'policy_check',
      decision: 'escalate',
    })
    expect(entries.total).toBeGreaterThan(0)

    const tamper = await api.demoTamper(true)
    expect(tamper.tampered).toBe(true)

    const apps = await api.listApplications()
    expect(apps.length).toBeGreaterThan(0)

    const created = await api.createApplication({
      name: 'UI Test Agent',
      environment: 'staging',
      process: 'procurement_review',
    })
    expect(created.api_key).toBeTruthy()

    const revoked = await api.revokeApplication(created.app_id)
    expect(revoked.status).toBe('revoked')
  })

  it('uploadDocument success and failure', async () => {
    const file = new File(['policy text'], 'policy.md', { type: 'text/markdown' })
    await expect(api.uploadDocument(file, 'procurement_review')).resolves.toMatchObject({
      ok: true,
      chunks: 3,
    })

    server.use(
      http.post('*/api/knowledge/documents', () =>
        HttpResponse.text('boom', { status: 500 }),
      ),
    )
    await expect(api.uploadDocument(file, 'procurement_review')).rejects.toThrow(/upload failed: 500/)
  })

  it('throws on non-ok JSON requests', async () => {
    server.use(http.get('*/api/health', () => HttpResponse.text('down', { status: 503 })))
    await expect(api.health()).rejects.toThrow(/GET \/health failed: 503/)
  })

  it('handles empty cases/approvals/applications bodies', async () => {
    server.use(
      http.get('*/api/cases', () => HttpResponse.json({})),
      http.get('*/api/approvals', () => HttpResponse.json({})),
      http.get('*/api/applications', () => HttpResponse.json({})),
    )
    await expect(api.listCases()).resolves.toEqual([])
    await expect(api.listApprovals()).resolves.toEqual([])
    await expect(api.listApplications()).resolves.toEqual([])
  })
})
