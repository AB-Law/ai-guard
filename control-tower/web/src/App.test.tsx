import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from './App'
import { renderApp } from './test/render'

describe('App routing integration', () => {
  it('redirects unauthenticated users to login', async () => {
    renderApp(<AppRoutes />, { route: '/', authenticated: false })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument())
  })

  it('navigates across main routes when authenticated', async () => {
    const user = userEvent.setup()
    renderApp(<AppRoutes />, { route: '/' })

    await waitFor(() => expect(screen.getByText('Live Traffic')).toBeInTheDocument())

    await user.click(screen.getByTitle('Approvals'))
    await waitFor(() => expect(screen.getByText('Approval queue')).toBeInTheDocument())

    await user.click(screen.getByTitle('Applications'))
    await waitFor(() =>
      expect(
        screen.getByText(/Every agent registered with the tower/i),
      ).toBeInTheDocument(),
    )

    await user.click(screen.getByTitle('Logs'))
    await waitFor(() => expect(screen.getByText(/Search every retrieval/i)).toBeInTheDocument())

    await user.click(screen.getByTitle('Audit & Integrity'))
    await waitFor(() => expect(screen.getByText('Audit & integrity')).toBeInTheDocument())

    await user.click(screen.getByTitle('Ops metrics'))
    await waitFor(() => expect(screen.getByText('Operational metrics')).toBeInTheDocument())

    await user.click(screen.getByTitle('Config'))
    await waitFor(() => expect(screen.getByText(/Config & knowledge base/i)).toBeInTheDocument())

    await user.click(screen.getByTitle('Overview'))
    await waitFor(() => expect(screen.getByText('Live Traffic')).toBeInTheDocument())
  })

  it('opens case detail from overview link', async () => {
    const user = userEvent.setup()
    renderApp(<AppRoutes />, { route: '/' })
    await waitFor(() => expect(screen.getByText('CASE-ALLOW')).toBeInTheDocument())
    await user.click(screen.getByRole('link', { name: 'CASE-ALLOW' }))
    await waitFor(() => expect(screen.getByText('Live traffic')).toBeInTheDocument())
    expect(screen.getByText('CASE-ALLOW')).toBeInTheDocument()
  })
})
