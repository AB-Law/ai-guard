import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth } from './auth'
import { UNAUTHORIZED_EVENT } from './api'

function Probe() {
  const { user, login, logout } = useAuth()
  return (
    <div>
      <div data-testid="email">{user?.email ?? 'none'}</div>
      <button type="button" onClick={() => login('a@b.com', 'secret')}>
        login
      </button>
      <button type="button" onClick={() => logout()}>
        logout
      </button>
    </div>
  )
}

describe('auth', () => {
  it('persists login and clears on logout', async () => {
    const user = userEvent.setup()
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(screen.getByTestId('email')).toHaveTextContent('none')
    await user.click(screen.getByText('login'))
    await waitFor(() => expect(screen.getByTestId('email')).toHaveTextContent('a@b.com'))
    expect(JSON.parse(localStorage.getItem('aegis.auth.user')!)).toEqual({ email: 'a@b.com' })
    expect(localStorage.getItem('aegis.auth.token')).toBe('test-token')
    await user.click(screen.getByText('logout'))
    expect(screen.getByTestId('email')).toHaveTextContent('none')
    expect(localStorage.getItem('aegis.auth.user')).toBeNull()
    expect(localStorage.getItem('aegis.auth.token')).toBeNull()
  })

  it('restores a stored user only when a token is also present', () => {
    localStorage.setItem('aegis.auth.user', JSON.stringify({ email: 'stored@aegis.dev' }))
    localStorage.setItem('aegis.auth.token', 'test-token')
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(screen.getByTestId('email')).toHaveTextContent('stored@aegis.dev')
  })

  it('ignores a stored user with no token (expired/cleared session)', () => {
    localStorage.setItem('aegis.auth.user', JSON.stringify({ email: 'stored@aegis.dev' }))
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(screen.getByTestId('email')).toHaveTextContent('none')
  })

  it('tolerates corrupt localStorage', () => {
    localStorage.setItem('aegis.auth.user', '{broken')
    localStorage.setItem('aegis.auth.token', 'test-token')
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(screen.getByTestId('email')).toHaveTextContent('none')
  })

  it('throws outside provider', () => {
    expect(() => render(<Probe />)).toThrow(/useAuth must be used within AuthProvider/)
  })

  it('signs out when a request reports 401 (token expired)', async () => {
    localStorage.setItem('aegis.auth.user', JSON.stringify({ email: 'x@y.com' }))
    localStorage.setItem('aegis.auth.token', 'test-token')
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(screen.getByTestId('email')).toHaveTextContent('x@y.com')
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    await waitFor(() => expect(screen.getByTestId('email')).toHaveTextContent('none'))
    expect(localStorage.getItem('aegis.auth.user')).toBeNull()
  })

  it('survives localStorage write failures', async () => {
    const user = userEvent.setup()
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    try {
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>,
      )
      await user.click(screen.getByText('login'))
      await waitFor(() => expect(screen.getByTestId('email')).toHaveTextContent('a@b.com'))
    } finally {
      setItem.mockRestore()
    }
  })

  it('logout ignores removeItem errors', async () => {
    const user = userEvent.setup()
    localStorage.setItem('aegis.auth.user', JSON.stringify({ email: 'x@y.com' }))
    localStorage.setItem('aegis.auth.token', 'test-token')
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    const spy = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    try {
      await user.click(screen.getByText('logout'))
      expect(screen.getByTestId('email')).toHaveTextContent('none')
    } finally {
      spy.mockRestore()
    }
  })
})
