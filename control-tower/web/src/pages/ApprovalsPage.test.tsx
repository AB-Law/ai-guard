import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { ApprovalsPage } from './ApprovalsPage'
import { AppShell } from '../components/layout/AppShell'
import { renderApp } from '../test/render'
import { server } from '../test/mocks/server'
import { http, HttpResponse } from 'msw'

function renderApprovals() {
  return renderApp(
    <AppShell>
      <Routes>
        <Route path="/approvals" element={<ApprovalsPage />} />
      </Routes>
    </AppShell>,
    { route: '/approvals' },
  )
}

describe('ApprovalsPage', () => {
  it('lists pending approvals and can approve', async () => {
    const user = userEvent.setup()
    renderApprovals()
    await waitFor(() => expect(screen.getByText('CASE-ESC')).toBeInTheDocument())
    expect(screen.getByText(/Awaiting decision/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Approve & resume/i }))
    await waitFor(() =>
      expect(screen.queryByText('CASE-ESC')).not.toBeInTheDocument(),
    )
  })

  it('can reject', async () => {
    const user = userEvent.setup()
    renderApprovals()
    await waitFor(() => expect(screen.getByText('CASE-ESC')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Reject' }))
    await waitFor(() =>
      expect(screen.queryByText('CASE-ESC')).not.toBeInTheDocument(),
    )
  })

  it('toggles API access panel', async () => {
    const user = userEvent.setup()
    renderApprovals()
    await waitFor(() => expect(screen.getByText('Approval queue')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /API access/i }))
    expect(screen.getByText(/Integrate this queue/i)).toBeInTheDocument()
    expect(screen.getByText(/GET \/approvals/)).toBeInTheDocument()
  })

  it('shows empty queue', async () => {
    server.use(
      http.get('*/api/approvals', () =>
        HttpResponse.json({ approvals: [], count: 0 }),
      ),
    )
    renderApprovals()
    await waitFor(() =>
      expect(screen.getByText(/Nothing waiting on a human/i)).toBeInTheDocument(),
    )
  })

  it('renders policy_change proposal, edits literal, and applies rule', async () => {
    const user = userEvent.setup()
    let body: { action?: string; rule_text?: string; actor?: string } = {}
    server.use(
      http.get('*/api/approvals', () =>
        HttpResponse.json({
          approvals: [
            {
              call_id: 'policy:rule-1',
              case_id: 'pol-rule1',
              process: 'procurement_review',
              origin: 'policy_change',
              tool_name: 'apply_learned_rule',
              reason: 'Proposed policy change from high-severity injection incident',
              risk_score: 90,
              confidence_score: 0.2,
              evidence_score: 0.3,
              policy_refs: ['incident:inc-1'],
              source_app: null,
              requested_at: new Date().toISOString(),
              rule_id: 'rule-1',
              rule_text: 'ignore prior instructions',
              matched_span_preview: 'ignore prior…',
              matched_span_hash: 'sha256:abcd',
              source_incident_id: 'inc-1',
            },
          ],
          count: 1,
        }),
      ),
      http.post('*/api/approvals/:callId', async ({ request }) => {
        body = (await request.json()) as typeof body
        return HttpResponse.json({
          case_id: 'pol-rule1',
          process: 'procurement_review',
          status: 'completed',
          call_id: 'policy:rule-1',
          origin: 'policy_change',
          gateway_decision: null,
          tool_result: null,
          request: null,
          source_app: null,
          created_at: new Date().toISOString(),
        })
      }),
    )

    renderApprovals()
    await waitFor(() => expect(screen.getByText('pol-rule1')).toBeInTheDocument())
    expect(screen.getByText('Policy change')).toBeInTheDocument()
    expect(screen.getByText('Proposed rule')).toBeInTheDocument()
    expect(screen.getByText('sha256:abcd')).toBeInTheDocument()

    const input = screen.getByDisplayValue('ignore prior instructions')
    await user.clear(input)
    await user.type(input, 'forget governance rules')
    await user.click(screen.getByRole('button', { name: /Apply rule/i }))

    await waitFor(() => expect(body.action).toBe('approve'))
    expect(body.rule_text).toBe('forget governance rules')
    expect(body.actor).toBeTruthy()
  })

  it('shows Applying… while policy approve is in flight', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('*/api/approvals', () =>
        HttpResponse.json({
          approvals: [
            {
              call_id: 'policy:rule-2',
              case_id: 'pol-rule2',
              process: 'finance',
              origin: 'policy_change',
              tool_name: 'apply_learned_rule',
              reason: 'proposal',
              risk_score: 80,
              confidence_score: null,
              evidence_score: null,
              policy_refs: [],
              source_app: null,
              requested_at: new Date().toISOString(),
              rule_id: 'rule-2',
              rule_text: 'skip budget',
              matched_span_preview: null,
              matched_span_hash: null,
              source_incident_id: 'inc-2',
            },
          ],
          count: 1,
        }),
      ),
      http.post('*/api/approvals/:callId', async () => {
        await new Promise((r) => setTimeout(r, 80))
        return HttpResponse.json({
          case_id: 'pol-rule2',
          status: 'completed',
          call_id: 'policy:rule-2',
          process: 'finance',
          origin: 'policy_change',
          gateway_decision: null,
          tool_result: null,
          request: null,
          source_app: null,
          created_at: new Date().toISOString(),
        })
      }),
    )

    renderApprovals()
    await waitFor(() => expect(screen.getByText('pol-rule2')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Apply rule/i }))
    expect(await screen.findByRole('button', { name: /Applying/i })).toBeInTheDocument()
  })
})
