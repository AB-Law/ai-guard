import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { OpsMetricsPage } from './OpsMetricsPage'
import { renderApp } from '../test/render'
import { server } from '../test/mocks/server'
import { opsMetricsEmpty } from '../test/mocks/data'

describe('OpsMetricsPage', () => {
  it('shows request volume, decision mix, latency, and token/cost data', async () => {
    renderApp(<OpsMetricsPage />)
    await waitFor(() => expect(screen.getByText('Operational metrics')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('Decision mix')).toBeInTheDocument())
    expect(screen.getByText('/guard/evaluate')).toBeInTheDocument()
    expect(screen.getByText('42.5 ms')).toBeInTheDocument()
    expect(screen.getByText('Prompt tokens')).toBeInTheDocument()
    expect(screen.getByText('1200')).toBeInTheDocument()
    expect(screen.getByText(/\$0\.006000 \(estimate\)/)).toBeInTheDocument()
  })

  it('shows empty and unavailable states when no data', async () => {
    server.use(http.get('*/api/ops/metrics', () => HttpResponse.json(opsMetricsEmpty)))
    renderApp(<OpsMetricsPage />)
    await waitFor(() =>
      expect(screen.getByText(/Empty — no requests or guard evaluations/i)).toBeInTheDocument(),
    )
    expect(screen.getByText(/Provider did not expose token usage/i)).toBeInTheDocument()
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
  })
})
