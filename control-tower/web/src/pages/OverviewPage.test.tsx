import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { OverviewPage } from './OverviewPage'
import { AppShell } from '../components/layout/AppShell'
import { renderApp } from '../test/render'
import { server } from '../test/mocks/server'
import { http, HttpResponse } from 'msw'

function renderOverview() {
  return renderApp(
    <AppShell>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
      </Routes>
    </AppShell>,
    { route: '/' },
  )
}

describe('OverviewPage', () => {
  it('renders KPIs and traffic rows', async () => {
    renderOverview()
    await waitFor(() => expect(screen.getByText('CASE-ALLOW')).toBeInTheDocument())
    expect(screen.getByText('Live Traffic')).toBeInTheDocument()
    expect(screen.getByText('Total cases')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('CASE-ESC')).toBeInTheDocument()
    expect(screen.getByText('CASE-BLOCK')).toBeInTheDocument()
  })

  it('filters by decision', async () => {
    const user = userEvent.setup()
    renderOverview()
    await waitFor(() => expect(screen.getByText('CASE-ALLOW')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Blocked' }))
    expect(screen.getByText('CASE-BLOCK')).toBeInTheDocument()
    expect(screen.queryByText('CASE-ALLOW')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Allowed' }))
    expect(screen.getByText('CASE-ALLOW')).toBeInTheDocument()
    expect(screen.queryByText('CASE-BLOCK')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Escalated' }))
    expect(screen.getByText('CASE-ESC')).toBeInTheDocument()
  })

  it('loads demo pack', async () => {
    const user = userEvent.setup()
    renderOverview()
    await waitFor(() => expect(screen.getByText('CASE-ALLOW')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Load demo pack/i }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Load demo pack/i })).not.toBeDisabled(),
    )
  })

  it('shows empty state', async () => {
    server.use(
      http.get('*/api/traffic/recent', () =>
        HttpResponse.json({
          cases: [],
          total_cases: 0,
          matched: 0,
          since_minutes: null,
          limit: 50,
        }),
      ),
    )
    renderOverview()
    await waitFor(() =>
      expect(screen.getByText(/No traffic yet/i)).toBeInTheDocument(),
    )
  })

  it('links to approvals from escalation KPI', async () => {
    renderOverview()
    await waitFor(() => expect(screen.getByText('CASE-ALLOW')).toBeInTheDocument())
    const link = screen.getByRole('link', { name: /view approvals/i })
    expect(link).toHaveAttribute('href', '/approvals')
  })
})
