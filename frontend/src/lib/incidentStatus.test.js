import { describe, expect, it } from 'vitest'
import { FALLBACK_SPEC as spec, nextOptions, normalizeStatus, statusMeta } from './incidentStatus'

describe('incident status machine (dashboard mirror)', () => {
  it('offers only allowed next statuses', () => {
    expect(nextOptions(spec, 'new', 'operator').map((s) => s.id))
      .toEqual(['acknowledged', 'verified_match', 'officer_dispatched', 'in_progress', 'closed', 'false_alarm'])
    expect(nextOptions(spec, 'target_located', 'operator').map((s) => s.id)).toEqual(['in_progress', 'resolved'])
  })

  it('closing and false alarm need a note and a confirmation', () => {
    const fa = nextOptions(spec, 'new', 'operator').find((s) => s.id === 'false_alarm')
    expect(fa.needsNote && fa.needsConfirm).toBe(true)
    expect(nextOptions(spec, 'new', 'operator').find((s) => s.id === 'acknowledged').needsNote).toBe(false)
  })

  it('only command roles re-open, and always with a note', () => {
    expect(nextOptions(spec, 'closed', 'operator')).toEqual([])
    const reopen = nextOptions(spec, 'closed', 'supervisor')
    expect(reopen.map((s) => s.id)).toEqual(['in_progress'])
    expect(reopen[0].needsNote).toBe(true)
  })

  it('reads legacy values', () => {
    expect(normalizeStatus('open')).toBe('new')
    expect(statusMeta(spec, 'investigating').label).toBe('In progress')
    expect(nextOptions(spec, 'investigating', 'operator').length).toBeGreaterThan(0)
  })
})
