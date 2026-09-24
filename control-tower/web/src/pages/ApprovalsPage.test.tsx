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
})
