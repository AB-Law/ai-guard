import { describe, expect, it, vi } from 'vitest'
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

  it('creates an application and shows one-time key', async () => {
    const user = userEvent.setup()
    renderApps()
    await waitFor(() => expect(screen.getByText('Claims Review Agent')).toBeInTheDocument())

    await user.click(screen.getAllByRole('button', { name: /New application/i })[0])
    await user.type(screen.getByPlaceholderText('Claims Review Agent'), 'Nightly Agent')
    await user.selectOptions(screen.getByDisplayValue('Production'), 'staging')
    await user.selectOptions(screen.getByDisplayValue('Select…'), 'procurement_review')
    await user.click(screen.getByRole('button', { name: /Create & generate key/i }))

    await waitFor(() =>
      expect(screen.getByText(/Nightly Agent connected/i)).toBeInTheDocument(),
    )
    expect(screen.getByText('aeg_live_secret_key_only_once')).toBeInTheDocument()

    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    await user.click(screen.getByRole('button', { name: /Copy/i }))
    expect(writeText).toHaveBeenCalledWith('aeg_live_secret_key_only_once')
  })

  it('opens create form from dashed card', async () => {
    const user = userEvent.setup()
    renderApps()
    await waitFor(() => expect(screen.getByText('Connect a new agent')).toBeInTheDocument())
    await user.click(screen.getByText('Connect a new agent'))
    expect(screen.getByPlaceholderText('Claims Review Agent')).toBeInTheDocument()
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

  it('tolerates clipboard failures', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockRejectedValueOnce(new Error('denied'))
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    renderApps()
    await waitFor(() => expect(screen.getByText('Claims Review Agent')).toBeInTheDocument())
    await user.click(screen.getAllByRole('button', { name: /New application/i })[0])
    await user.type(screen.getByPlaceholderText('Claims Review Agent'), 'Clip Agent')
    await user.selectOptions(screen.getByDisplayValue('Select…'), 'procurement_review')
    await user.click(screen.getByRole('button', { name: /Create & generate key/i }))
    await waitFor(() => expect(screen.getByText(/Clip Agent connected/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Copy/i }))
    expect(writeText).toHaveBeenCalled()
  })
})
