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
    expect(screen.getByText('create_purchase_order')).toBeInTheDocument()
    expect(screen.getByText('send_payment')).toBeInTheDocument()

    await user.click(screen.getByText('Onboarding KYC'))
    await waitFor(() => expect(screen.getByText('verify_identity')).toBeInTheDocument())
    expect(screen.getByText(/No documents indexed yet/i)).toBeInTheDocument()
  })

  it('uploads a document', async () => {
    const user = userEvent.setup()
    renderConfig()
    await waitFor(() => expect(screen.getByText('create_purchase_order')).toBeInTheDocument())

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
    await waitFor(() => expect(screen.getByText('create_purchase_order')).toBeInTheDocument())
    const file = new File(['x'], 'bad.md', { type: 'text/markdown' })
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, file)
    await waitFor(() => expect(screen.getByText(/upload failed: 400/i)).toBeInTheDocument())
  })
})
