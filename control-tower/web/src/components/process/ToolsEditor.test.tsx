import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { ToolsEditor, type ToolsValue } from './ToolsEditor'

function Harness({
  initial,
  onChange,
  evidenceDocOptions,
}: {
  initial: ToolsValue
  onChange?: (v: ToolsValue) => void
  evidenceDocOptions?: string[]
}) {
  const [value, setValue] = useState(initial)
  return (
    <ToolsEditor
      value={value}
      onChange={(next) => {
        setValue(next)
        onChange?.(next)
      }}
      evidenceDocOptions={evidenceDocOptions}
    />
  )
}

const withTool: ToolsValue = {
  allowedTools: [{ name: 'create_purchase_order', max_auto_amount: 10000, unit: 'usd' }],
  disallowedTools: ['send_payment'],
  approvalThreshold: 60,
}

describe('ToolsEditor', () => {
  it('adds and removes an allow-listed tool row', async () => {
    const user = userEvent.setup()
    render(<Harness initial={{ allowedTools: [], disallowedTools: [], approvalThreshold: 60 }} />)

    expect(screen.queryByText('Tool name')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Add tool/i }))
    expect(screen.getByText('Tool name')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('n/a')).toBeDisabled()

    await user.click(screen.getByRole('button', { name: /Remove tool/i }))
    expect(screen.queryByText('Tool name')).not.toBeInTheDocument()
  })

  it('edits a tool name, ceiling, and unit', async () => {
    const user = userEvent.setup()
    render(<Harness initial={withTool} />)

    const nameInput = screen.getByDisplayValue('create_purchase_order')
    await user.clear(nameInput)
    await user.type(nameInput, 'issue_refund')
    expect(screen.getByDisplayValue('issue_refund')).toBeInTheDocument()

    const ceilingInput = screen.getByDisplayValue('10000')
    await user.clear(ceilingInput)
    await user.type(ceilingInput, '500')
    expect(screen.getByDisplayValue('500')).toBeInTheDocument()

    const unitInput = screen.getByDisplayValue('usd')
    expect(unitInput).toBeEnabled()
    await user.clear(unitInput)
    await user.type(unitInput, 'eur')
    expect(screen.getByDisplayValue('eur')).toBeInTheDocument()

    await user.clear(ceilingInput)
    expect(screen.getByPlaceholderText('no ceiling')).toBeInTheDocument()
  })

  it('updates disallowed tools on blur', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness initial={withTool} onChange={onChange} />)

    const disallowedInput = screen.getByDisplayValue('send_payment')
    await user.clear(disallowedInput)
    await user.type(disallowedInput, 'wire_transfer, delete_records')
    await user.tab()

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ disallowedTools: ['wire_transfer', 'delete_records'] }),
    )
  })

  it('toggles required evidence docs when options are provided', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <Harness
        initial={{ ...withTool, requiredEvidenceDocs: [] }}
        onChange={onChange}
        evidenceDocOptions={['finance_policy', 'kyc_policy']}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'finance_policy' }))
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ requiredEvidenceDocs: ['finance_policy'] }),
    )
  })
})
