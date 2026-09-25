import { describe, expect, it } from 'vitest'
import {
  evidenceEnumFromSchema,
  fieldErrorMap,
  knownToolsFromSchema,
  slugifyProcessId,
  validateAgainstSchema,
} from './processSchema'
import type { ProcessConfigPayload } from './api'

const schema: Record<string, unknown> = {
  title: 'ProcessConfig',
  type: 'object',
  required: [
    'process',
    'allowed_tools',
    'disallowed_tools',
    'required_evidence_docs',
    'approval_threshold',
    'knowledge_base_paths',
  ],
  properties: {
    process: { type: 'string', minLength: 1 },
    title: { type: ['string', 'null'] },
    allowed_tools: { type: 'array' },
    disallowed_tools: { type: 'array', items: { type: 'string' } },
    required_evidence_docs: {
      type: 'array',
      items: { type: 'string', enum: ['finance_policy', 'kyc_policy'] },
    },
    approval_threshold: {
      type: 'object',
      properties: { risk_score_gte: { type: 'integer', minimum: 0, maximum: 100 } },
      required: ['risk_score_gte'],
    },
    knowledge_base_paths: { type: 'array', items: { type: 'string' } },
  },
  'x-known-tools': ['approve_claim', 'create_purchase_order'],
}

function payload(overrides: Partial<ProcessConfigPayload> = {}): ProcessConfigPayload {
  return {
    process: 'claims_review',
    title: 'Claims',
    allowed_tools: [],
    disallowed_tools: [],
    required_evidence_docs: [],
    approval_threshold: { risk_score_gte: 60 },
    knowledge_base_paths: [],
    ...overrides,
  }
}

describe('processSchema', () => {
  it('extracts evidence enum and known tools from schema', () => {
    expect(evidenceEnumFromSchema(schema)).toEqual(['finance_policy', 'kyc_policy'])
    expect(knownToolsFromSchema(schema)).toEqual(['approve_claim', 'create_purchase_order'])
    expect(evidenceEnumFromSchema({})).toEqual([])
    expect(knownToolsFromSchema({})).toEqual([])
  })

  it('slugifies process ids from titles', () => {
    expect(slugifyProcessId('Claims Review')).toBe('claims_review')
    expect(slugifyProcessId('  Foo!!Bar  ')).toBe('foo_bar')
  })

  it('maps field errors to dotted keys', () => {
    expect(
      fieldErrorMap([
        { loc: ['required_evidence_docs', 0], msg: 'bad', type: 'unknown_evidence_doc' },
        { loc: [], msg: 'form', type: 'value_error' },
      ]),
    ).toEqual({
      'required_evidence_docs.0': 'bad',
      _form: 'form',
    })
  })

  it('validates payloads against the JSON schema', () => {
    expect(validateAgainstSchema(schema, payload())).toEqual([])
    const errors = validateAgainstSchema(
      schema,
      payload({ required_evidence_docs: ['not_real'], approval_threshold: { risk_score_gte: 200 } }),
    )
    expect(errors.length).toBeGreaterThan(0)
    expect(errors.some((e) => e.loc.includes('required_evidence_docs') || e.msg.includes('enum'))).toBe(
      true,
    )
  })
})
