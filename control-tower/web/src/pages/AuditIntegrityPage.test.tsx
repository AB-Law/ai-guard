import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { AuditIntegrityPage } from './AuditIntegrityPage'
import { AppShell } from '../components/layout/AppShell'
import { renderApp } from '../test/render'
import { server } from '../test/mocks/server'
import { http, HttpResponse } from 'msw'

function renderAudit() {
  return renderApp(
    <AppShell>
      <Routes>
        <Route path="/audit" element={<AuditIntegrityPage />} />
      </Routes>
    </AppShell>,
    { route: '/audit' },
  )
}

describe('AuditIntegrityPage', () => {
  it('shows intact chain and can simulate tamper', async () => {
    const user = userEvent.setup()
    renderAudit()
    await waitFor(() =>
      expect(screen.getByText(/Chain intact/i)).toBeInTheDocument(),
    )
    expect(screen.getByText('Log entries')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Simulate tamper/i }))
    await waitFor(() =>
      expect(screen.getByText(/Chain broken at entry/i)).toBeInTheDocument(),
    )
    expect(screen.getByText('MISMATCH')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Undo tamper demo/i }))
    await waitFor(() => expect(screen.getByText(/Chain intact/i)).toBeInTheDocument())
  })

  it('shows empty log state', async () => {
    server.use(
      http.get('*/api/audit/entries', () =>
        HttpResponse.json({ entries: [], total: 0, limit: 200, offset: 0 }),
      ),
    )
    renderAudit()
    await waitFor(() =>
      expect(screen.getByText(/No audit entries yet/i)).toBeInTheDocument(),
    )
  })
})
