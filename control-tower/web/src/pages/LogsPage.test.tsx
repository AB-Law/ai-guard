import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { LogsPage } from './LogsPage'
import { AppShell } from '../components/layout/AppShell'
import { renderApp } from '../test/render'

function renderLogs() {
  return renderApp(
    <AppShell>
      <Routes>
        <Route path="/logs" element={<LogsPage />} />
      </Routes>
    </AppShell>,
    { route: '/logs' },
  )
}

describe('LogsPage', () => {
  it('lists audit entries and expands payload', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))
    expect(screen.getAllByText('policy_check').length).toBeGreaterThan(0)

    const injectionBtn = screen.getAllByText('injection_flag')[0].closest('button')!
    await user.click(injectionBtn)
    await waitFor(() =>
      expect(screen.getByText(/Ignore previous instructions/)).toBeInTheDocument(),
    )
  })

  it('filters via facets and search', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    await user.click(screen.getAllByRole('button', { name: /onboarding_kyc/i })[0])
    expect(screen.getAllByText('tool_call').length).toBeGreaterThan(0)
    expect(screen.queryByText('injection_flag')).not.toBeInTheDocument()

    await user.clear(screen.getByPlaceholderText(/process:onboarding_kyc/))
    await user.type(
      screen.getByPlaceholderText(/process:onboarding_kyc/),
      'event_type:approval',
    )
    await waitFor(() => expect(screen.getAllByText('approval').length).toBeGreaterThan(0))
  })

  it('toggles live tail and uses autocomplete', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getByText(/Search every retrieval/i)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /Live tail/i }))
    expect(screen.getByRole('button', { name: /Paused/i })).toBeInTheDocument()

    const input = screen.getByPlaceholderText(/process:onboarding_kyc/)
    await user.type(input, 'proc')
    await waitFor(() => expect(screen.getByText('process:')).toBeInTheDocument())
    await user.keyboard('{ArrowDown}{Enter}')
  })

  it('shows no-match empty state', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))
    await user.type(screen.getByPlaceholderText(/process:onboarding_kyc/), 'zzzz-no-match')
    await waitFor(() =>
      expect(screen.getByText(/No entries match this query/i)).toBeInTheDocument(),
    )
  })
})
