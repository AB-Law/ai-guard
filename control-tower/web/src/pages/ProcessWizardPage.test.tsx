import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { ProcessWizardPage } from './ProcessWizardPage'
import { AppShell } from '../components/layout/AppShell'
import { renderApp } from '../test/render'
import { server } from '../test/mocks/server'

function renderWizard() {
  return renderApp(
    <AppShell>
      <Routes>
        <Route path="/processes/new" element={<ProcessWizardPage />} />
        <Route path="/applications" element={<div>applications page</div>} />
      </Routes>
    </AppShell>,
    { route: '/processes/new' },
  )
}

describe('ProcessWizardPage', () => {
  it('creates a new process, sets thresholds, writes a policy, and connects an agent', async () => {
    const user = userEvent.setup()
    renderWizard()

    // Step 1 — create new process (default mode)
    await user.type(screen.getByPlaceholderText('Claims Review'), 'Claims Review')
    await user.click(screen.getByRole('button', { name: 'Next' }))

    // Step 2 — thresholds
    await waitFor(() => expect(screen.getByText(/Guardrails for/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Add tool/i }))
    await user.type(screen.getByPlaceholderText('tool_name'), 'approve_claim')
    await user.click(screen.getByRole('button', { name: 'Next' }))

    // Step 3 — policy
    await waitFor(() => expect(screen.getByText(/Knowledge base —/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Next' }))

    // Step 4 — connect agent
    await waitFor(() => expect(screen.getByText(/Connect the agent/i)).toBeInTheDocument())
    await user.type(screen.getByPlaceholderText('Claims Review Agent'), 'Claims Bot')
    await user.click(screen.getByRole('button', { name: /Create & generate key/i }))

    await waitFor(() => expect(screen.getByText(/is connected to Claims Review/i)).toBeInTheDocument())
    expect(screen.getByText('aeg_live_secret_key_only_once')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(screen.getByText('applications page')).toBeInTheDocument())
  })

  it('supports picking an existing process instead of creating one', async () => {
    const user = userEvent.setup()
    renderWizard()

    await user.click(screen.getByRole('button', { name: 'Use an existing process' }))
    await waitFor(() => expect(screen.getByText('Procurement Review')).toBeInTheDocument())
    await user.click(screen.getByText('Procurement Review'))
    await user.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(screen.getByText(/Guardrails for/i)).toBeInTheDocument())
    expect(screen.getByDisplayValue('create_purchase_order')).toBeInTheDocument()
  })

  it('requires a title before advancing when creating a new process', async () => {
    const user = userEvent.setup()
    renderWizard()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText(/Give the new process a name/i)).toBeInTheDocument()
  })

  it('steps back from thresholds and from policy', async () => {
    const user = userEvent.setup()
    renderWizard()

    await user.type(screen.getByPlaceholderText('Claims Review'), 'Back Nav Test')
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText(/Guardrails for/i)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByPlaceholderText('Claims Review')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText(/Guardrails for/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText(/Knowledge base —/i)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Back' }))
    await waitFor(() => expect(screen.getByText(/Guardrails for/i)).toBeInTheDocument())
  })

  it('switches environment and copies the generated key', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    renderWizard()

    await user.type(screen.getByPlaceholderText('Claims Review'), 'Env Test')
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText(/Guardrails for/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText(/Knowledge base —/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(screen.getByText(/Connect the agent/i)).toBeInTheDocument())
    await user.selectOptions(screen.getByDisplayValue('Production'), 'staging')
    await user.type(screen.getByPlaceholderText('Claims Review Agent'), 'Env Bot')
    await user.click(screen.getByRole('button', { name: /Create & generate key/i }))

    await waitFor(() => expect(screen.getByText(/is connected to Env Test/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Copy/i }))
    expect(writeText).toHaveBeenCalledWith('aeg_live_secret_key_only_once')
  })

  it('surfaces an error when connecting the agent fails', async () => {
    const user = userEvent.setup()
    renderWizard()

    await user.click(screen.getByRole('button', { name: 'Use an existing process' }))
    await waitFor(() => expect(screen.getByText('Procurement Review')).toBeInTheDocument())
    await user.click(screen.getByText('Procurement Review'))
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText(/Guardrails for/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText(/Knowledge base —/i)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText(/Connect the agent/i)).toBeInTheDocument())

    server.use(http.post('*/api/applications', () => HttpResponse.text('boom', { status: 500 })))
    await user.type(screen.getByPlaceholderText('Claims Review Agent'), 'Failing Bot')
    await user.click(screen.getByRole('button', { name: /Create & generate key/i }))

    expect(await screen.findByText(/failed: 500/i)).toBeInTheDocument()
  })
})
