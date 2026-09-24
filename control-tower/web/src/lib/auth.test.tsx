import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth } from './auth'

function Probe() {
  const { user, login, logout } = useAuth()
  return (
    <div>
      <div data-testid="email">{user?.email ?? 'none'}</div>
      <button type="button" onClick={() => login('a@b.com')}>
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
    expect(screen.getByTestId('email')).toHaveTextContent('a@b.com')
    expect(JSON.parse(localStorage.getItem('aegis.auth.user')!)).toEqual({ email: 'a@b.com' })
    await user.click(screen.getByText('logout'))
    expect(screen.getByTestId('email')).toHaveTextContent('none')
    expect(localStorage.getItem('aegis.auth.user')).toBeNull()
  })

  it('restores stored user', () => {
    localStorage.setItem('aegis.auth.user', JSON.stringify({ email: 'stored@aegis.dev' }))
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(screen.getByTestId('email')).toHaveTextContent('stored@aegis.dev')
  })

  it('tolerates corrupt localStorage', () => {
    localStorage.setItem('aegis.auth.user', '{broken')
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
      expect(screen.getByTestId('email')).toHaveTextContent('a@b.com')
    } finally {
      setItem.mockRestore()
    }
  })

  it('logout ignores removeItem errors', async () => {
    const user = userEvent.setup()
    localStorage.setItem('aegis.auth.user', JSON.stringify({ email: 'x@y.com' }))
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
