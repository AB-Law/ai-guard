import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Button } from './Button'
import { Badge } from './Badge'
import { Card } from './Card'
import { Input } from './Input'
import { StageDots } from '../StageDots'
import { Sidebar } from '../layout/Sidebar'
import { ProtectedRoute } from '../ProtectedRoute'
import { AuthProvider } from '../../lib/auth'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ActiveProcessProvider } from '../../lib/processConfig'

describe('UI primitives', () => {
  it('renders Button variants', () => {
    const { rerender } = render(<Button>Go</Button>)
    expect(screen.getByRole('button', { name: 'Go' })).toBeEnabled()
    rerender(
      <Button variant="accent" size="lg" disabled>
        Busy
      </Button>,
    )
    expect(screen.getByRole('button', { name: 'Busy' })).toBeDisabled()
  })

  it('renders Badge tones', () => {
    render(
      <>
        <Badge tone="success">ok</Badge>
        <Badge tone="warning" dot={false}>
          warn
        </Badge>
      </>,
    )
    expect(screen.getByText('ok')).toBeInTheDocument()
    expect(screen.getByText('warn')).toBeInTheDocument()
  })

  it('renders Card and Input', () => {
    render(
      <Card>
        <Input placeholder="name" defaultValue="x" />
      </Card>,
    )
    expect(screen.getByPlaceholderText('name')).toHaveValue('x')
  })
})

describe('StageDots', () => {
  it('colors stages for allow / escalate / block', () => {
    const { container, rerender } = render(
      <StageDots stages={['retrieval', 'policy_check', 'tool_call']} decision="allow" status="completed" />,
    )
    expect(container.querySelectorAll('[style]').length).toBeGreaterThan(0)

    rerender(
      <StageDots
        stages={['retrieval', 'injection_flag', 'policy_check', 'approval']}
        decision="escalate"
        status="pending_approval"
      />,
    )
    rerender(
      <StageDots stages={['retrieval', 'policy_check', 'tool_call']} decision="block" status="blocked" />,
    )
  })
})

describe('Sidebar', () => {
  it('shows approval badge count', () => {
    render(
      <AuthProvider>
        <MemoryRouter>
          <Sidebar pendingApprovals={3} />
        </MemoryRouter>
      </AuthProvider>,
    )
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByTitle('Investigate')).toBeInTheDocument()
  })
})

describe('ProtectedRoute', () => {
  it('redirects when logged out', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <ActiveProcessProvider>
            <MemoryRouter initialEntries={['/']}>
              <ProtectedRoute>
                <div>secret</div>
              </ProtectedRoute>
            </MemoryRouter>
          </ActiveProcessProvider>
        </AuthProvider>
      </QueryClientProvider>,
    )
    expect(screen.queryByText('secret')).not.toBeInTheDocument()
  })
})
