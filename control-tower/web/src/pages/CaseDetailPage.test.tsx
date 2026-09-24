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
})
