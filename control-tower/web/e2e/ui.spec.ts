import { test, expect, type Page } from '@playwright/test'

/** Stub every /api call so Playwright never touches the real tower DB. */
async function mockApi(page: Page) {
  const caseRow = {
    case_id: 'CASE-ALLOW',
    process: 'procurement_review',
    status: 'completed',
    call_id: 'call-1',
    gateway_decision: {
      call_id: 'call-1',
      decision: 'allow',
      reason: 'ok',
      policy_refs: [],
      risk_score: 10,
      confidence_score: 0.9,
      evidence_score: 0.9,
    },
    tool_result: { ok: true },
    request: {},
    source_app: 'demo',
    created_at: new Date().toISOString(),
  }

  const traffic = {
    cases: [
      {
        case_id: 'CASE-ALLOW',
        process: 'procurement_review',
        status: 'completed',
        decision: 'allow',
        risk_score: 10,
        reason: 'ok',
        tool_name: 'create_purchase_order',
        stages: ['retrieval', 'policy_check', 'tool_call'],
        source_app: 'demo',
        created_at: caseRow.created_at,
      },
      {
        case_id: 'CASE-ESC',
        process: 'procurement_review',
        status: 'pending_approval',
        decision: 'escalate',
        risk_score: 80,
        reason: 'high',
        tool_name: 'create_purchase_order',
        stages: ['retrieval', 'policy_check', 'approval'],
        source_app: 'demo',
        created_at: caseRow.created_at,
      },
    ],
    total_cases: 2,
    matched: 2,
    since_minutes: null,
    limit: 50,
  }

  const configs = {
    processes: [
      {
        id: 'procurement_review',
        title: 'Procurement Review',
        config_path: 'configs/procurement_review.yaml',
        allowed_tools: [{ name: 'create_purchase_order', max_auto_amount: 10000, unit: 'usd' }],
        disallowed_tools: ['send_payment'],
        approval_threshold: { risk_score_gte: 60 },
        seed_docs: ['a.md'],
        uploaded_docs: [],
      },
    ],
  }

  const approvals = [
    {
      call_id: 'call-esc',
      case_id: 'CASE-ESC',
      process: 'procurement_review',
      tool_name: 'create_purchase_order',
      reason: 'high',
      risk_score: 80,
      confidence_score: 0.7,
      evidence_score: 0.6,
      policy_refs: [],
      source_app: 'demo',
      requested_at: caseRow.created_at,
    },
  ]

  const entries = [
    {
      entry_id: 'e1',
      process: 'procurement_review',
      step_id: 'g',
      event_type: 'policy_check',
      payload: { case_id: 'CASE-ALLOW' },
      scores: caseRow.gateway_decision,
      timestamp: caseRow.created_at,
      prev_hash: '0'.repeat(64),
      entry_hash: 'a'.repeat(64),
    },
  ]

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/^\/api/, '') || url.pathname
    const method = route.request().method()

    const json = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      })

    if (path.endsWith('/health') || path === '/health') return json({ status: 'ok' })
    if (path.includes('/traffic/recent')) return json(traffic)
    if (path.endsWith('/cases') && method === 'GET') return json({ cases: [caseRow] })
    if (path.match(/\/cases\/[^/]+\/audit$/)) return json({ case_id: 'CASE-ALLOW', entries, chain_valid: true })
    if (path.match(/\/cases\/[^/]+$/) && method === 'GET') {
      const id = path.split('/').pop()
      return json({ ...caseRow, case_id: id })
    }
    if (path.endsWith('/approvals') && method === 'GET') return json({ approvals, count: approvals.length })
    if (path.includes('/approvals/') && method === 'POST') return json({ ...caseRow, status: 'completed' })
    if (path.endsWith('/configs')) return json(configs)
    if (path.endsWith('/applications') && method === 'GET') return json({ applications: [] })
    if (path.endsWith('/applications') && method === 'POST') {
      return json({
        app_id: 'new',
        name: 'E2E Agent',
        environment: 'staging',
        process: 'procurement_review',
        source_app: 'e2e',
        status: 'connected',
        key_display: 'aeg_••••e2e',
        api_key: 'aeg_e2e_secret',
        created_at: caseRow.created_at,
        revoked_at: null,
        requests_today: 0,
        last_seen: null,
      })
    }
    if (path.includes('/revoke')) {
      return json({
        app_id: 'x',
        name: 'x',
        environment: 'staging',
        process: 'procurement_review',
        source_app: 'x',
        status: 'revoked',
        key_display: 'aeg_••••',
        created_at: caseRow.created_at,
        revoked_at: caseRow.created_at,
        requests_today: 0,
        last_seen: null,
      })
    }
    if (path.endsWith('/audit/verify')) return json({ valid: true, entry_count: 1, first_invalid_entry_id: null })
    if (path.includes('/audit/entries')) return json({ entries, total: 1, limit: 200, offset: 0 })
    if (path.includes('/audit/demo-tamper')) return json({ tampered: true, entry_id: 'e1' })
    if (path.includes('/demo/seed')) return json({ ok: true, cases: [caseRow], pending_approval_count: 1 })
    if (path.includes('/demo/reset')) return json({ ok: true })
    if (path.includes('/knowledge/documents')) return json({ ok: true, chunks: 1 })
    if (path.includes('/investigate')) return json({ answer: 'ok', sources: [] })

    return json({ detail: `unmocked ${method} ${path}` }, 404)
  })
}

async function login(page: Page) {
  await page.goto('/login')
  await page.getByRole('button', { name: 'Continue as demo user' }).click()
  await expect(page.getByText('Live Traffic')).toBeVisible()
}

test.describe('Control Tower UI (mocked API)', () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page)
  })

  test('login → overview → filter → case detail', async ({ page }) => {
    await login(page)
    await expect(page.getByText('CASE-ALLOW')).toBeVisible()
    await page.getByRole('button', { name: 'Escalated', exact: true }).click()
    await expect(page.getByText('CASE-ESC')).toBeVisible()
    await page.getByRole('button', { name: 'All', exact: true }).click()
    await page.getByRole('link', { name: 'CASE-ALLOW' }).click()
    await expect(page.getByText('Gateway decision').first()).toBeVisible()
  })

  test('approvals approve flow', async ({ page }) => {
    await login(page)
    await page.getByTitle('Approvals').click()
    await expect(page.getByText('Approval queue')).toBeVisible()
    await page.getByRole('button', { name: /Approve & resume/i }).click()
  })

  test('applications create key', async ({ page }) => {
    await login(page)
    await page.getByTitle('Applications').click()
    await page.getByRole('button', { name: /New application/i }).click()
    await page.getByPlaceholder('Claims Review Agent').fill('E2E Agent')
    await page.locator('select').nth(1).selectOption('procurement_review')
    await page.getByRole('button', { name: /Create & generate key/i }).click()
    await expect(page.getByText(/E2E Agent connected/i)).toBeVisible()
    await expect(page.getByText('aeg_e2e_secret')).toBeVisible()
  })

  test('logs, audit, config pages load', async ({ page }) => {
    await login(page)

    await page.getByTitle('Logs').click()
    await expect(page.getByText(/Search every retrieval/i)).toBeVisible()
    await expect(page.getByText('policy_check').first()).toBeVisible()

    await page.getByTitle('Audit & Integrity').click()
    await expect(page.getByText(/Chain intact/i)).toBeVisible()

    await page.getByTitle('Config').click()
    await expect(page.getByText('Procurement Review').first()).toBeVisible()
    await expect(page.getByText('create_purchase_order')).toBeVisible()
  })

  test('guards unauthenticated routes', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  })
})
