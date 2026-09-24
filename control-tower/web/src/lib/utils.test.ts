import { describe, expect, it } from 'vitest'
import {
  cn,
  decisionBadgeTone,
  decisionLabel,
  relativeTime,
  riskColor,
} from '../lib/utils'

describe('cn', () => {
  it('merges class names and resolves conflicts', () => {
    expect(cn('px-2', 'px-4', false && 'hidden', 'text-sm')).toContain('px-4')
    expect(cn('px-2', 'px-4')).not.toContain('px-2')
  })
})

describe('relativeTime', () => {
  it('handles null and invalid', () => {
    expect(relativeTime(null)).toBe('—')
    expect(relativeTime(undefined)).toBe('—')
    expect(relativeTime('not-a-date')).toBe('—')
  })

  it('formats recent times', () => {
    expect(relativeTime(new Date().toISOString())).toBe('just now')
    expect(relativeTime(new Date(Date.now() - 15_000).toISOString())).toBe('15s ago')
    expect(relativeTime(new Date(Date.now() - 120_000).toISOString())).toBe('2m ago')
    expect(relativeTime(new Date(Date.now() - 7200_000).toISOString())).toBe('2h ago')
    expect(relativeTime(new Date(Date.now() - 172800_000).toISOString())).toBe('2d ago')
  })
})

describe('riskColor', () => {
  it('maps bands', () => {
    expect(riskColor(null)).toContain('muted')
    expect(riskColor(20)).toContain('success')
    expect(riskColor(50)).toContain('warning')
    expect(riskColor(80)).toContain('danger')
  })
})

describe('decision helpers', () => {
  it('maps tones and labels', () => {
    expect(decisionBadgeTone('allow')).toBe('success')
    expect(decisionBadgeTone('escalate')).toBe('warning')
    expect(decisionBadgeTone('block')).toBe('danger')
    expect(decisionBadgeTone(null)).toBe('muted')

    expect(decisionLabel('allow', 'completed')).toBe('Allowed')
    expect(decisionLabel('block', 'blocked')).toBe('Blocked')
    expect(decisionLabel('escalate', 'completed')).toBe('Escalated')
    expect(decisionLabel(null, 'pending_approval')).toBe('Escalated')
    expect(decisionLabel(null, 'running')).toBe('Running')
  })
})
