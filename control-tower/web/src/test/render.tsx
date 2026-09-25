import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderOptions } from '@testing-library/react'
import { MemoryRouter, type MemoryRouterProps } from 'react-router-dom'
import type { ReactElement, ReactNode } from 'react'
import { AuthProvider } from '../lib/auth'
import { ActiveProcessProvider } from '../lib/processConfig'
import { resetMockState } from './mocks/server'

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0, refetchInterval: false },
      mutations: { retry: false },
    },
  })
}

export function loginAs(email = 'demo@aegis.dev') {
  localStorage.setItem('aegis.auth.user', JSON.stringify({ email }))
  localStorage.setItem('aegis.auth.token', 'test-token')
}

interface Options extends Omit<RenderOptions, 'wrapper'> {
  route?: string
  routes?: MemoryRouterProps['initialEntries']
  authenticated?: boolean
}

export function renderApp(ui: ReactElement, options: Options = {}) {
  const { route = '/', routes, authenticated = true, ...rest } = options
  resetMockState()
  if (authenticated) loginAs()
  else {
    localStorage.removeItem('aegis.auth.user')
    localStorage.removeItem('aegis.auth.token')
  }

  const client = createTestQueryClient()
  const initialEntries = routes ?? [route]

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <AuthProvider>
          <ActiveProcessProvider>
            <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
          </ActiveProcessProvider>
        </AuthProvider>
      </QueryClientProvider>
    )
  }

  return { ...render(ui, { wrapper: Wrapper, ...rest }), client }
}
