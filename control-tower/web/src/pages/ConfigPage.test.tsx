import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { ConfigPage } from './ConfigPage'
import { AppShell } from '../components/layout/AppShell'
import { renderApp } from '../test/render'
import { server } from '../test/mocks/server'
import { http, HttpResponse } from 'msw'

function renderConfig() {
  return renderApp(
    <AppShell>
      <Routes>
        <Route path="/config" element={<ConfigPage />} />
      </Routes>
    </AppShell>,
    { route: '/config' },
  )
}

describe('ConfigPage', () => {
  it('lists processes and switches active process', async () => {
    const user = userEvent.setup()
    renderConfig()
    await waitFor(() => expect(screen.getByText('Procurement Review')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByDisplayValue('create_purchase_order')).toBeInTheDocument())

    await user.click(screen.getByText('Onboarding KYC'))
    await waitFor(() => expect(screen.getByDisplayValue('verify_identity')).toBeInTheDocument())
    expect(screen.getByText(/No documents indexed yet/i)).toBeInTheDocument()
  })

  it('shows uploaded and custom docs with distinct tags', async () => {
    renderConfig()
    await waitFor(() => expect(screen.getByText('extra-policy.md')).toBeInTheDocument())
    expect(screen.getByText('custom-note.md')).toBeInTheDocument()
    expect(screen.getByText('uploaded')).toBeInTheDocument()
    expect(screen.getByText('custom')).toBeInTheDocument()
  })

  it('uploads a document', async () => {
    const user = userEvent.setup()
    renderConfig()
    await waitFor(() => expect(screen.getByDisplayValue('create_purchase_order')).toBeInTheDocument())

    const file = new File(['# policy'], 'extra.md', { type: 'text/markdown' })
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    expect(input).toBeTruthy()
    await user.upload(input, file)

    await waitFor(() =>
      expect(screen.getByText(/extra\.md indexed into Procurement Review/i)).toBeInTheDocument(),
    )
  })

  it('surfaces upload errors', async () => {
    const user = userEvent.setup()
    server.use(
      http.post('*/api/knowledge/documents', () =>
        HttpResponse.text('nope', { status: 400 }),
      ),
    )
    renderConfig()
    await waitFor(() => expect(screen.getByDisplayValue('create_purchase_order')).toBeInTheDocument())
    const file = new File(['x'], 'bad.md', { type: 'text/markdown' })
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, file)
    await waitFor(() => expect(screen.getByText(/upload failed: 400/i)).toBeInTheDocument())
  })

  it('writes a new custom policy from the editor', async () => {
    const user = userEvent.setup()
    renderConfig()
    await waitFor(() => expect(screen.getByText('extra-policy.md')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /Write a policy/i }))
    await user.type(screen.getByPlaceholderText(/Policy title/i), 'New Escalation Rule')
    await user.type(screen.getByPlaceholderText(/Write the policy text/i), 'Escalate anything over $9,000.')
    await user.click(screen.getByRole('button', { name: 'Save policy' }))

    await waitFor(() =>
      expect(screen.getByText(/"New Escalation Rule" indexed into Procurement Review/i)).toBeInTheDocument(),
    )
  })

  it('edits an existing custom policy in place', async () => {
    const user = userEvent.setup()
    renderConfig()
    await waitFor(() => expect(screen.getByText('custom-note.md')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Edit custom-note.md' }))
    await waitFor(() => expect(screen.getByDisplayValue(/Original custom note body\./i)).toBeInTheDocument())

    const textarea = screen.getByDisplayValue(/Original custom note body\./i)
    await user.clear(textarea)
    await user.type(textarea, 'Updated custom note body.')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(screen.getByText(/"custom-note" updated/i)).toBeInTheDocument())
  })

  it('deletes a document', async () => {
    const user = userEvent.setup()
    renderConfig()
    await waitFor(() => expect(screen.getByText('extra-policy.md')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Delete extra-policy.md' }))
    await waitFor(() =>
      expect(screen.getByText(/Document removed from the knowledge base/i)).toBeInTheDocument(),
    )
  })

  it('edits thresholds and saves', async () => {
    const user = userEvent.setup()
    renderConfig()
    await waitFor(() => expect(screen.getByDisplayValue('create_purchase_order')).toBeInTheDocument())

    const thresholdInput = screen.getByDisplayValue('60')
    await user.clear(thresholdInput)
    await user.type(thresholdInput, '75')

    const saveButton = await screen.findByRole('button', { name: 'Save changes' })
    await user.click(saveButton)
    await waitFor(() => expect(screen.getByText('Saved.')).toBeInTheDocument())
  })
})
