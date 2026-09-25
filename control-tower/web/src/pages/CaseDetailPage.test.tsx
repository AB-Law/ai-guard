import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { CaseDetailPage } from './CaseDetailPage'
import { AppShell } from '../components/layout/AppShell'
import { renderApp } from '../test/render'
import { server } from '../test/mocks/server'
import { http, HttpResponse } from 'msw'
import { cases, gatewayEscalate } from '../test/mocks/data'

function renderCase(caseId: string) {
  return renderApp(
    <AppShell>
      <Routes>
        <Route path="/cases/:caseId" element={<CaseDetailPage />} />
      </Routes>
    </AppShell>,
    { route: `/cases/${caseId}` },
  )
}

describe('CaseDetailPage', () => {
  it('renders case pipeline and scores', async () => {
    const user = userEvent.setup()
    renderCase('CASE-ESC')
    await waitFor(() => expect(screen.getByText('CASE-ESC')).toBeInTheDocument())
    expect(screen.getByText('Prompt injection detected')).toBeInTheDocument()
    expect(screen.getByText(/Ignore previous instructions/i)).toBeInTheDocument()
    expect(screen.getAllByText('Gateway decision').length).toBeGreaterThan(0)
    expect(screen.getAllByText(gatewayEscalate.reason).length).toBeGreaterThan(0)

    await user.click(screen.getByText('Confidence'))
    expect(screen.getByText(/How closely the agent/i)).toBeInTheDocument()

    await user.click(screen.getByText('Evidence (groundedness)'))
    expect(
      screen.getByText(/matched to a retrieved passage|Claim:|could not be matched/i),
    ).toBeInTheDocument()
  })

  it('shows allow case without injection banner', async () => {
    renderCase('CASE-ALLOW')
    await waitFor(() => expect(screen.getByText('CASE-ALLOW')).toBeInTheDocument())
    expect(screen.queryByText('Prompt injection detected')).not.toBeInTheDocument()
    expect(screen.getAllByText('allow').length).toBeGreaterThan(0)
  })

  it('shows loading state while fetching', async () => {
    server.use(
      http.get('*/api/cases/:caseId', async () => {
        await new Promise((r) => setTimeout(r, 50))
        return HttpResponse.json(cases[0])
      }),
    )
    renderCase('CASE-ALLOW')
    expect(screen.getByText(/Fetching case/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('CASE-ALLOW')).toBeInTheDocument())
  })

  it('renders policy_change proposal card with hashed span', async () => {
    server.use(
      http.get('*/api/cases/:caseId', () =>
        HttpResponse.json({
          case_id: 'pol-abc',
          process: 'procurement_review',
          status: 'pending_approval',
          call_id: 'policy:abc',
          origin: 'policy_change',
          gateway_decision: {
            call_id: 'policy:abc',
            decision: 'escalate',
            reason: 'Proposed policy change',
            policy_refs: ['incident:inc-9'],
            risk_score: 90,
            confidence_score: 0.1,
            evidence_score: 0.2,
          },
          tool_result: null,
          request: {
            tool_name: 'apply_learned_rule',
            rule_text: 'ignore prior instructions',
            source_incident_id: 'inc-9',
            matched_span_preview: 'ignore prior…',
            matched_span_hash: 'sha256:deadbeef',
          },
          source_app: null,
          created_at: new Date().toISOString(),
        }),
      ),
      http.get('*/api/cases/:caseId/audit', () =>
        HttpResponse.json({ case_id: 'pol-abc', entries: [], chain_valid: true }),
      ),
    )
    renderCase('pol-abc')
    await waitFor(() => expect(screen.getByText('pol-abc')).toBeInTheDocument())
    expect(screen.getByText('Policy change')).toBeInTheDocument()
    expect(screen.getByText('Proposed learned rule')).toBeInTheDocument()
    expect(screen.getByText('ignore prior instructions')).toBeInTheDocument()
    expect(screen.getByText('sha256:deadbeef')).toBeInTheDocument()
    expect(screen.getByText('apply_learned_rule')).toBeInTheDocument()
  })
})
