/** Client-side ProcessConfig validation against GET /processes/schema. */

import Ajv2020, { type ErrorObject } from 'ajv/dist/2020'
import type { FieldError, ProcessConfigPayload } from '../lib/api'

const ajv = new Ajv2020({ allErrors: true, strict: false })

export function evidenceEnumFromSchema(schema: Record<string, unknown>): string[] {
  const props = schema.properties as Record<string, unknown> | undefined
  const req = props?.required_evidence_docs as { items?: { enum?: string[] } } | undefined
  return req?.items?.enum ?? []
}

export function knownToolsFromSchema(schema: Record<string, unknown>): string[] {
  const tools = schema['x-known-tools']
  return Array.isArray(tools) ? tools.filter((t): t is string => typeof t === 'string') : []
}

function ajvPathToLoc(instancePath: string): (string | number)[] {
  if (!instancePath || instancePath === '/') return []
  return instancePath
    .replace(/^\//, '')
    .split('/')
    .map((part) => (/^\d+$/.test(part) ? Number(part) : part.replace(/~1/g, '/').replace(/~0/g, '~')))
}

export function validateAgainstSchema(
  schema: Record<string, unknown>,
  data: ProcessConfigPayload,
): FieldError[] {
  const validate = ajv.compile(schema)
  const ok = validate(data)
  if (ok || !validate.errors) return []
  return validate.errors.map((err: ErrorObject) => ({
    loc: ajvPathToLoc(err.instancePath),
    msg: err.message ?? 'invalid',
    type: err.keyword,
  }))
}

/** Map server/client field errors onto form field keys for inline display. */
export function fieldErrorMap(errors: FieldError[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const err of errors) {
    const key = err.loc.map(String).join('.') || '_form'
    if (!out[key]) out[key] = err.msg
  }
  return out
}

export function slugifyProcessId(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}
