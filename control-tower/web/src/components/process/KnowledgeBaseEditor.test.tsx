import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { KnowledgeBaseEditor } from './KnowledgeBaseEditor'
import { resetMockState } from '../../test/mocks/server'

function renderEditor() {
  resetMockState()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <KnowledgeBaseEditor
        processId="procurement_review"
        processTitle="Procurement Review"
        seedDocs={['policies/procurement.md']}
        uploadedDocs={[
          { name: 'extra-policy.md', kind: 'uploaded', path: 'extra-policy.md' },
          { name: 'custom-note.md', kind: 'custom', path: 'custom/custom-note.md' },
        ]}
      />
    </QueryClientProvider>,
  )
}

describe('KnowledgeBaseEditor', () => {
  it('clicking the dropzone opens the hidden file picker', async () => {
    const user = userEvent.setup()
    renderEditor()
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const clickSpy = vi.spyOn(input, 'click')
    await user.click(screen.getByText(/Drop a \.md/i))
    expect(clickSpy).toHaveBeenCalled()
  })

  it('cancels composing a new policy without saving', async () => {
    const user = userEvent.setup()
    renderEditor()
    await user.click(screen.getByRole('button', { name: /Write a policy/i }))
    expect(screen.getByPlaceholderText(/Policy title/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByPlaceholderText(/Policy title/i)).not.toBeInTheDocument()
  })

  it('edits the title while editing a custom policy, then cancels', async () => {
    const user = userEvent.setup()
    renderEditor()
    await user.click(screen.getByRole('button', { name: 'Edit custom-note.md' }))
    await waitFor(() => expect(screen.getByDisplayValue('custom-note')).toBeInTheDocument())

    const titleInput = screen.getByDisplayValue('custom-note')
    await user.clear(titleInput)
    await user.type(titleInput, 'Renamed Note')
    expect(screen.getByDisplayValue('Renamed Note')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByDisplayValue('Renamed Note')).not.toBeInTheDocument()
  })
})
