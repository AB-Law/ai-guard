import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useActiveProcess } from './processConfig'
import { renderApp } from '../test/render'
import { waitFor } from '@testing-library/react'

function Probe() {
  const { active, processes, setActiveId } = useActiveProcess()
  return (
    <div>
      <div data-testid="active">{active?.id ?? 'none'}</div>
      <div data-testid="count">{processes.length}</div>
      <button type="button" onClick={() => setActiveId('onboarding_kyc')}>
        switch
      </button>
    </div>
  )
}

function Outside() {
  useActiveProcess()
  return null
}

describe('processConfig', () => {
  it('loads processes and persists active selection', async () => {
    const user = userEvent.setup()
    renderApp(<Probe />)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('2'))
    await waitFor(() =>
      expect(screen.getByTestId('active')).toHaveTextContent('procurement_review'),
    )
    await user.click(screen.getByText('switch'))
    expect(screen.getByTestId('active')).toHaveTextContent('onboarding_kyc')
    expect(localStorage.getItem('aegis.activeProcessId')).toBe('onboarding_kyc')
  })

  it('selects first process when stored id is unknown', async () => {
    localStorage.setItem('aegis.activeProcessId', 'missing-process')
    renderApp(<Probe />)
    await waitFor(() =>
      expect(screen.getByTestId('active')).toHaveTextContent('procurement_review'),
    )
  })

  it('throws outside provider', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    expect(() =>
      render(
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <Outside />
          </MemoryRouter>
        </QueryClientProvider>,
      ),
    ).toThrow(/useActiveProcess must be used within ActiveProcessProvider/)
  })
})
