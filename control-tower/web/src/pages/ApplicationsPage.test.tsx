import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { ApplicationsPage } from './ApplicationsPage'
import { AppShell } from '../components/layout/AppShell'
import { renderApp } from '../test/render'
import { server } from '../test/mocks/server'
import { http, HttpResponse } from 'msw'

function renderApps() {
  return renderApp(
    <AppShell>
      <Routes>
        <Route path="/applications" element={<ApplicationsPage />} />
      </Routes>
    </AppShell>,
    { route: '/applications' },
  )
}

describe('ApplicationsPage', () => {
  it('lists applications and revokes connected ones', async () => {
    const user = userEvent.setup()
    renderApps()
    await waitFor(() => expect(screen.getByText('Claims Review Agent')).toBeInTheDocument())
    expect(screen.getByText('Staging Bot')).toBeInTheDocument()
    expect(screen.getByText(/Declared MCP servers/i)).toBeInTheDocument()
    expect(screen.getByText(/Self-reported connections/i)).toBeInTheDocument()
    expect(screen.getByText(/Observed traffic/i)).toBeInTheDocument()

    const revokeButtons = screen.getAllByRole('button', { name: 'Revoke' })
    await user.click(revokeButtons[0])
    await waitFor(() => expect(screen.getAllByText('Revoked').length).toBeGreaterThan(0))
  })

  it('filters by environment, process, and status', async () => {
    const user = userEvent.setup()
    renderApps()
    await waitFor(() => expect(screen.getByText('Claims Review Agent')).toBeInTheDocument())

    await user.selectOptions(screen.getByLabelText('Environment'), 'staging')
    expect(screen.queryByText('Claims Review Agent')).not.toBeInTheDocument()
    expect(screen.getByText('Staging Bot')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Environment'), 'all')
    await user.selectOptions(screen.getByLabelText('Process'), 'procurement_review')
    expect(screen.getByText('Claims Review Agent')).toBeInTheDocument()
    expect(screen.queryByText('Staging Bot')).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Process'), 'all')
    await user.selectOptions(screen.getByLabelText('Status'), 'revoked')
    expect(screen.getByText('Staging Bot')).toBeInTheDocument()
    expect(screen.queryByText('Claims Review Agent')).not.toBeInTheDocument()
  })

  it('links to the connect-agent wizard from the header and the dashed card', async () => {
    renderApps()
    await waitFor(() => expect(screen.getByText('Claims Review Agent')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: /New application/i })).toHaveAttribute('href', '/processes/new')
    expect(screen.getByRole('link', { name: /Connect a new agent/i })).toHaveAttribute('href', '/processes/new')
  })

  it('shows empty state', async () => {
    server.use(
      http.get('*/api/applications', () => HttpResponse.json({ applications: [] })),
    )
    renderApps()
    await waitFor(() =>
      expect(screen.getByText(/No applications registered yet/i)).toBeInTheDocument(),
    )
  })

  it('shows no-match empty state when filters exclude everything', async () => {
    const user = userEvent.setup()
    renderApps()
    await waitFor(() => expect(screen.getByText('Claims Review Agent')).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText('Status'), 'online')
    expect(screen.getByText(/No applications match the current filters/i)).toBeInTheDocument()
    // Ensure the filter controls themselves are still mounted.
    expect(within(document.body).getByLabelText('Status')).toBeInTheDocument()
  })
})
