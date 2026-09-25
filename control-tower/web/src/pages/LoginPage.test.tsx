import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { LoginPage } from './LoginPage'
import { renderApp } from '../test/render'

describe('LoginPage', () => {
  it('signs in with email + password and navigates home', async () => {
    const user = userEvent.setup()
    renderApp(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>home</div>} />
      </Routes>,
      { route: '/login', authenticated: false },
    )

    await user.type(screen.getByPlaceholderText('you@company.com'), 'ops@aegis.dev')
    await user.type(screen.getByPlaceholderText('••••••••'), 'secret')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(screen.getByText('home')).toBeInTheDocument())
    expect(JSON.parse(localStorage.getItem('aegis.auth.user')!).email).toBe('ops@aegis.dev')
    expect(localStorage.getItem('aegis.auth.token')).toBe('test-token')
  })

  it('defaults to demo email when blank', async () => {
    const user = userEvent.setup()
    renderApp(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>home</div>} />
      </Routes>,
      { route: '/login', authenticated: false },
    )
    await user.type(screen.getByPlaceholderText('••••••••'), 'secret')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByText('home')).toBeInTheDocument())
    expect(JSON.parse(localStorage.getItem('aegis.auth.user')!).email).toBe('demo@aegis.dev')
  })

  it('shows an error on a rejected password', async () => {
    const user = userEvent.setup()
    renderApp(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>home</div>} />
      </Routes>,
      { route: '/login', authenticated: false },
    )
    await user.type(screen.getByPlaceholderText('••••••••'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() =>
      expect(screen.getByText(/wrong password/i)).toBeInTheDocument(),
    )
  })
})
