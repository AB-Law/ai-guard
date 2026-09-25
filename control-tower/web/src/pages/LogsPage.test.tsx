import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { LogsPage } from './LogsPage'
import { AppShell } from '../components/layout/AppShell'
import { renderApp } from '../test/render'

// jsdom never computes real layout, so histogram bars report a zero-width
// rect by default. Stub it so mouse-position math (bucket = x / width) in
// the component resolves to a predictable bucket index in tests.
function stubHistogramRect() {
  const hist = screen.getByTestId('histogram')
  vi.spyOn(hist, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    right: 360,
    width: 360,
    top: 0,
    bottom: 64,
    height: 64,
    x: 0,
    y: 0,
    toJSON: () => {},
  } as DOMRect)
  return hist
}

function renderLogs() {
  return renderApp(
    <AppShell>
      <Routes>
        <Route path="/logs" element={<LogsPage />} />
      </Routes>
    </AppShell>,
    { route: '/logs' },
  )
}

describe('LogsPage', () => {
  it('lists audit entries and expands and collapses payload', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))
    expect(screen.getAllByText('policy_check').length).toBeGreaterThan(0)

    // The sidebar "Event type" facet also renders an "injection_flag" label;
    // the last match in document order is the table row's own badge.
    const injectionBtn = screen.getAllByText('injection_flag').at(-1)!.closest('button')!
    await user.click(injectionBtn)
    await waitFor(() =>
      expect(screen.getByTestId('expanded-payload-entry-2')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('expanded-payload-entry-2')).toHaveTextContent(/Ignore previous instructions/)

    await user.click(injectionBtn)
    await waitFor(() =>
      expect(screen.queryByTestId('expanded-payload-entry-2')).not.toBeInTheDocument(),
    )
  })

  it('filters via facets and search', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    await user.click(screen.getAllByRole('button', { name: /onboarding_kyc/i })[0])
    expect(screen.getAllByText('tool_call').length).toBeGreaterThan(0)
    expect(screen.queryByText('injection_flag')).not.toBeInTheDocument()

    await user.clear(screen.getByPlaceholderText(/process:onboarding_kyc/))
    await user.type(
      screen.getByPlaceholderText(/process:onboarding_kyc/),
      'event_type:approval',
    )
    await waitFor(() => expect(screen.getAllByText('approval').length).toBeGreaterThan(0))
  })

  it('filters by case id and via the decision facet', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    await user.type(screen.getByPlaceholderText(/process:onboarding_kyc/), 'case:CASE-ESC')
    await waitFor(() => expect(screen.getAllByText('policy_check').length).toBeGreaterThan(0))
    expect(screen.queryByText('output_claim')).not.toBeInTheDocument()

    await user.clear(screen.getByPlaceholderText(/process:onboarding_kyc/))
    await waitFor(() => expect(screen.getAllByText('output_claim').length).toBeGreaterThan(0))

    const blockFacetBtn = screen.getAllByRole('button', { name: /block/i }).find((b) => b.textContent?.includes('block'))!
    await user.click(blockFacetBtn)
    await waitFor(() => expect(screen.getByPlaceholderText(/process:onboarding_kyc/)).toHaveValue('decision:block'))
  })

  it('toggles live tail and uses autocomplete', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getByText(/Search every retrieval/i)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /Live tail/i }))
    expect(screen.getByRole('button', { name: /Paused/i })).toBeInTheDocument()

    const input = screen.getByPlaceholderText(/process:onboarding_kyc/)
    await user.type(input, 'proc')
    await waitFor(() => expect(screen.getByText('process:')).toBeInTheDocument())
    await user.keyboard('{ArrowDown}{ArrowUp}{Enter}')
    expect(input).toHaveValue('process:')

    await user.keyboard('{Escape}')

    await user.clear(input)
    await user.type(input, 'event_type:tool')
    await waitFor(() => expect(screen.getByText('event_type:tool_call')).toBeInTheDocument())
    await user.click(screen.getByText('event_type:tool_call'))
    expect(input).toHaveValue('event_type:tool_call ')
  })

  it('does not suggest values for an unrecognized field prefix', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getByText(/Search every retrieval/i)).toBeInTheDocument())

    const input = screen.getByPlaceholderText(/process:onboarding_kyc/)
    await user.type(input, 'bogus:x')
    expect(screen.queryByText('process:')).not.toBeInTheDocument()
  })

  it('shows no-match empty state', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))
    await user.type(screen.getByPlaceholderText(/process:onboarding_kyc/), 'zzzz-no-match')
    await waitFor(() =>
      expect(screen.getByText(/No entries match this query/i)).toBeInTheDocument(),
    )
  })

  it('switches the quick range and resets a manual time selection made before it', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    const rangeButton = screen.getByTestId('quick-range-button')
    expect(rangeButton).toHaveTextContent('Live')

    // Select a single histogram bucket to open a manual time-range filter.
    const hist = stubHistogramRect()
    const bar0 = screen.getByTestId('hist-bar-0')
    fireEvent.mouseDown(bar0)
    fireEvent.mouseUp(hist)
    expect(screen.getByTestId('time-range-chip')).toBeInTheDocument()

    await user.click(rangeButton)
    await user.click(screen.getByRole('button', { name: '1 hour' }))

    expect(rangeButton).toHaveTextContent('1 hour')
    // Switching the quick range clears whatever manual bucket was selected.
    expect(screen.queryByTestId('time-range-chip')).not.toBeInTheDocument()
  })

  it('shows every quick-range option in the dropdown', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    await user.click(screen.getByTestId('quick-range-button'))
    for (const label of ['Live', '15 mins', '1 hour', '4 hours', '1 day', '1 week']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
  })

  it('hovering a histogram bucket shows a tooltip with the decision breakdown', async () => {
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    const hist = stubHistogramRect()
    expect(screen.queryByTestId('hist-tooltip')).not.toBeInTheDocument()

    fireEvent.mouseMove(hist, { clientX: 5, clientY: 100 })
    const tooltip = await screen.findByTestId('hist-tooltip')
    expect(tooltip).toHaveTextContent(/allow \d+/)
    expect(tooltip).toHaveTextContent(/escalate \d+/)
    expect(tooltip).toHaveTextContent(/block \d+/)

    fireEvent.mouseLeave(hist)
    expect(screen.queryByTestId('hist-tooltip')).not.toBeInTheDocument()
  })

  it('clicking a single histogram bucket toggles a time-range filter on and off', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    const hist = stubHistogramRect()
    const bar0 = screen.getByTestId('hist-bar-0')

    fireEvent.mouseDown(bar0)
    fireEvent.mouseUp(hist)
    expect(screen.getByTestId('time-range-chip')).toBeInTheDocument()

    // Clicking the very same bucket again clears the selection.
    fireEvent.mouseDown(bar0)
    fireEvent.mouseUp(hist)
    expect(screen.queryByTestId('time-range-chip')).not.toBeInTheDocument()

    // Re-select, then use the explicit clear button.
    fireEvent.mouseDown(bar0)
    fireEvent.mouseUp(hist)
    await user.click(screen.getByText(/Clear time filter/))
    expect(screen.queryByTestId('time-range-chip')).not.toBeInTheDocument()
  })

  it('dragging across histogram buckets selects a wider time range', async () => {
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    const hist = stubHistogramRect()
    const bar0 = screen.getByTestId('hist-bar-0')

    fireEvent.mouseDown(bar0)
    fireEvent.mouseMove(hist, { clientX: 300, clientY: 30 })
    fireEvent.mouseUp(hist)

    expect(screen.getByTestId('time-range-chip')).toBeInTheDocument()
  })

  it('a drag that leaves the histogram still finalizes the selection', async () => {
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    const hist = stubHistogramRect()
    const bar0 = screen.getByTestId('hist-bar-0')

    fireEvent.mouseDown(bar0)
    fireEvent.mouseMove(hist, { clientX: 200, clientY: 30 })
    fireEvent.mouseLeave(hist)

    expect(screen.getByTestId('time-range-chip')).toBeInTheDocument()
    expect(screen.queryByTestId('hist-tooltip')).not.toBeInTheDocument()
  })

  it('clicking a decision segment in the histogram filters the table by that decision', async () => {
    const user = userEvent.setup()
    renderLogs()
    await waitFor(() => expect(screen.getAllByText('injection_flag').length).toBeGreaterThan(0))

    stubHistogramRect()
    const input = screen.getByPlaceholderText(/process:onboarding_kyc/) as HTMLInputElement

    await user.click(screen.getByTestId('hist-decision-escalate-0'))
    expect(input).toHaveValue('decision:escalate')
    await waitFor(() => expect(screen.getByText(/escalate — risk 78/)).toBeInTheDocument())
    expect(screen.queryByText('output_claim')).not.toBeInTheDocument()

    // Clicking the same decision segment again clears the filter.
    await user.click(screen.getByTestId('hist-decision-escalate-0'))
    expect(input).toHaveValue('')
    await waitFor(() => expect(screen.getAllByText('output_claim').length).toBeGreaterThan(0))

    // Clicking a different decision color swaps the active filter.
    await user.click(screen.getByTestId('hist-decision-block-0'))
    expect(input).toHaveValue('decision:block')
    await user.click(screen.getByTestId('hist-decision-allow-0'))
    expect(input).toHaveValue('decision:allow')
  })
})
