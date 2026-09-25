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

  it('renders evidence card from retrieval, policy, and tool audit entries', async () => {
    const user = userEvent.setup()
    const now = new Date().toISOString()
    server.use(
      http.get('*/api/cases/:caseId', () =>
        HttpResponse.json({
          case_id: 'CASE-EVIDENCE',
          process: 'procurement_review',
          status: 'blocked',
          call_id: 'call-evidence-1',
          gateway_decision: {
            call_id: 'call-evidence-1',
            decision: 'block',
            reason: 'Disallowed tool',
            policy_refs: ['policy:allow_list'],
            risk_score: 95,
            confidence_score: 0.9,
            evidence_score: 0.3,
          },
          tool_result: null,
          request: { vendor_id: 'V-9' },
          source_app: 'claims-agent',
          created_at: now,
        }),
      ),
      http.get('*/api/cases/:caseId/audit', () =>
        HttpResponse.json({
          case_id: 'CASE-EVIDENCE',
          chain_valid: true,
          entries: [
            {
              entry_id: 'e-ret',
              process: 'procurement_review',
              step_id: 'retrieve',
              event_type: 'retrieval',
              payload: {
                case_id: 'CASE-EVIDENCE',
                chunks: [
                  {
                    id: 'chunk-1',
                    source: 'policies/procurement.md',
                    excerpt: 'Payments require dual approval.',
                  },
                ],
              },
              scores: null,
              timestamp: now,
              prev_hash: '0'.repeat(64),
              entry_hash: 'a'.repeat(64),
            },
            {
              entry_id: 'e-pol',
              process: 'procurement_review',
              step_id: 'gateway',
              event_type: 'policy_check',
              payload: {
                case_id: 'CASE-EVIDENCE',
                unsupported_claims: ['Vendor waived approval'],
                entailment: { violated_clauses: ['clause:dual-control'] },
              },
              scores: null,
              timestamp: now,
              prev_hash: 'a'.repeat(64),
              entry_hash: 'b'.repeat(64),
            },
            {
              entry_id: 'e-tool',
              process: 'procurement_review',
              step_id: 'tool',
              event_type: 'tool_call',
              payload: {
                case_id: 'CASE-EVIDENCE',
                tool_name: 'send_payment',
                tool_args: { amount: 9000 },
              },
              scores: null,
              timestamp: now,
              prev_hash: 'b'.repeat(64),
              entry_hash: 'c'.repeat(64),
            },
          ],
        }),
      ),
    )
    renderCase('CASE-EVIDENCE')
    await waitFor(() => expect(screen.getByText('CASE-EVIDENCE')).toBeInTheDocument())
    expect(screen.getByText('Evidence')).toBeInTheDocument()
    expect(screen.getByText('policies/procurement.md (chunk-1)')).toBeInTheDocument()
    expect(screen.getByText('Vendor waived approval')).toBeInTheDocument()
    expect(screen.getByText(/policy:allow_list, clause:dual-control/)).toBeInTheDocument()
    expect(screen.getByText(/Proposed: send_payment\(\{"amount":9000\}\)/)).toBeInTheDocument()
    expect(screen.getByText(/Actual: Blocked — not executed/)).toBeInTheDocument()

    await user.click(screen.getByText('Confidence'))
    await user.click(screen.getByText('Risk score'))
    expect(screen.getByText(/Risk score — 95 \/ 100/)).toBeInTheDocument()
  })

  it('shows tool result as actual action when executed', async () => {
    const now = new Date().toISOString()
    server.use(
      http.get('*/api/cases/:caseId', () =>
        HttpResponse.json({
          ...cases[0],
          case_id: 'CASE-TOOL-RESULT',
          tool_result: { ok: true, po_id: 'PO-1' },
        }),
      ),
      http.get('*/api/cases/:caseId/audit', () =>
        HttpResponse.json({
          case_id: 'CASE-TOOL-RESULT',
          chain_valid: true,
          entries: [
            {
              entry_id: 'e-tool',
              process: 'procurement_review',
              step_id: 'tool',
              event_type: 'tool_call',
              payload: { case_id: 'CASE-TOOL-RESULT', tool_name: 'create_purchase_order' },
              scores: null,
              timestamp: now,
              prev_hash: '0'.repeat(64),
              entry_hash: 'a'.repeat(64),
            },
          ],
        }),
      ),
    )
    renderCase('CASE-TOOL-RESULT')
    await waitFor(() => expect(screen.getByText('CASE-TOOL-RESULT')).toBeInTheDocument())
    expect(screen.getByText(/Actual: \{"ok":true,"po_id":"PO-1"\}/)).toBeInTheDocument()
    expect(screen.getByText('No documents retrieved for this case.')).toBeInTheDocument()
    expect(screen.getByText('No passage recorded.')).toBeInTheDocument()
  })
})
