import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { renderApp } from '../test/render'

describe('DevelopersPage', () => {
  it('renders the public route with README content and a link to applications', async () => {
    renderApp(<AppRoutes />, { route: '/developers', authenticated: false })

    expect(await screen.findByTitle('Developers')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /create_agent/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Plain Python' })).toBeInTheDocument()
    expect(document.body.textContent).toContain('AiGuardMiddleware')
    expect(screen.getByRole('link', { name: /get an api key/i })).toHaveAttribute('href', '/applications')
  })

  it('jumps to a section and highlights it from the page nav', async () => {
    const user = userEvent.setup()
    const scrollIntoView = vi.fn()
    HTMLElement.prototype.scrollIntoView = scrollIntoView

    renderApp(<AppRoutes />, { route: '/developers', authenticated: false })
    await screen.findByRole('heading', { name: 'Setup' })

    await user.click(screen.getByRole('button', { name: 'Setup' }))
    expect(scrollIntoView).toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Setup' }).className).toContain('text-accent')
  })

  it('copies a code block and reports failures', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })

    renderApp(<AppRoutes />, { route: '/developers', authenticated: false })
    await screen.findByRole('heading', { name: 'Install' })

    const copyButtons = screen.getAllByRole('button', { name: 'Copy code' })
    await user.click(copyButtons[0])
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Copied' }).length).toBeGreaterThan(0))
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('pip install'))

    writeText.mockRejectedValueOnce(new Error('denied'))
    await user.click(screen.getByRole('button', { name: 'Copied' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Copied' })).not.toBeInTheDocument())
  })

  it('updates the active section from scroll position', async () => {
    let callback: IntersectionObserverCallback | undefined
    class FakeObserver implements IntersectionObserver {
      readonly root = null
      readonly rootMargin = ''
      readonly scrollMargin = ''
      readonly thresholds = []
      constructor(cb: IntersectionObserverCallback) {
        callback = cb
      }
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords(): IntersectionObserverEntry[] {
        return []
      }
    }
    vi.stubGlobal('IntersectionObserver', FakeObserver)

    renderApp(<AppRoutes />, { route: '/developers', authenticated: false })
    const heading = await screen.findByRole('heading', { name: 'Escalation' })
    const install = screen.getByRole('heading', { name: 'Install' })
    callback?.(
      [
        { isIntersecting: true, intersectionRatio: 0.2, target: install } as unknown as IntersectionObserverEntry,
        { isIntersecting: true, intersectionRatio: 1, target: heading } as unknown as IntersectionObserverEntry,
        { isIntersecting: false, intersectionRatio: 0, target: install } as unknown as IntersectionObserverEntry,
      ],
      {} as IntersectionObserver,
    )
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Escalation' }).className).toContain('text-accent'),
    )
    vi.unstubAllGlobals()
  })
})
