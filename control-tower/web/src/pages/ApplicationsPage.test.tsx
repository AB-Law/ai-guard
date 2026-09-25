import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
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

    const revokeButtons = screen.getAllByRole('button', { name: 'Revoke' })
    await user.click(revokeButtons[0])
    await waitFor(() => expect(screen.getAllByText('Revoked').length).toBeGreaterThan(0))
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
})
