import { describe, expect, it } from 'vitest'
import { fromAlertRow, groupRepeats, waitLabel, waitUrgency } from './events'

const at = (min) => new Date(Date.UTC(2026, 10, 22, 12, min)).toISOString().replace('Z', '')
const alert = (id, min, extra = {}) => ({ id, type: 'SUSPICIOUS_BEHAVIOR', cameraId: 'lab', personName: null, time: at(min), ...extra })

describe('groupRepeats', () => {
  it('folds a run of the same alert into its newest entry', () => {
    const [g, ...rest] = groupRepeats([alert(1, 0), alert(2, 6), alert(3, 12)])
    expect(rest).toEqual([])
    expect(g.id).toBe(3)
    expect(g.repeats).toEqual([3, 2, 1])
    expect(g.since).toBe(at(0))
  })
  it('starts a new entry after a gap longer than the window', () => {
    const groups = groupRepeats([alert(1, 0), alert(2, 30)], 10 * 60 * 1000)
    expect(groups.map((g) => g.repeats)).toEqual([[2], [1]])
  })
  it('keeps different cameras, people and types apart', () => {
    const groups = groupRepeats([
      alert(1, 0), alert(2, 1, { cameraId: 'gate' }), alert(3, 2, { personName: 'Sadik' }),
      alert(4, 3, { type: 'FALL_SUSPECTED' }),
    ])
    expect(groups).toHaveLength(4)
  })
})

describe('fromAlertRow', () => {
  it('maps API fields and defaults', () => {
    const a = fromAlertRow({ id: 9, alert_type: 'WEAPON_DETECTED', camera_id: 'c1', camera_location: 'Gate' })
    expect(a).toMatchObject({ id: 9, type: 'WEAPON_DETECTED', camera: 'Gate', cameraId: 'c1', severity: 'info', reviewStatus: 'not_required' })
  })
})

describe('waiting timers', () => {
  it('formats short and long waits', () => {
    expect(waitLabel(45)).toBe('0:45')
    expect(waitLabel(723)).toBe('12:03')
    expect(waitLabel(7500)).toBe('2 h 05 min')
    expect(waitLabel(-3)).toBe('0:00')
  })
  const esc = { after: 120, types: ['CRIMINAL_DETECTED', 'WEAPON_DETECTED'] }
  const t0 = Date.UTC(2026, 10, 22, 12, 0)
  const item = (type, extra = {}) => ({ type, time: new Date(t0).toISOString(), ...extra })
  it('counts escalating alerts against the paging limit', () => {
    expect(waitUrgency(item('WEAPON_DETECTED'), t0 + 30_000, esc)).toBe('ok')
    expect(waitUrgency(item('WEAPON_DETECTED'), t0 + 61_000, esc)).toBe('warn')
    expect(waitUrgency(item('CRIMINAL_DETECTED'), t0 + 121_000, esc)).toBe('danger')
  })
  it('gives other alerts ten minutes, and resolved ones no timer', () => {
    expect(waitUrgency(item('FALL_SUSPECTED'), t0 + 300_000, esc)).toBe('ok')
    expect(waitUrgency(item('FALL_SUSPECTED'), t0 + 601_000, esc)).toBe('warn')
    expect(waitUrgency(item('WEAPON_DETECTED', { acknowledged: true }), t0 + 999_000, esc)).toBeNull()
  })
  it('times a group of repeats from its first alert', () => {
    const g = item('WEAPON_DETECTED', { time: new Date(t0 + 100_000).toISOString(), since: new Date(t0).toISOString() })
    expect(waitUrgency(g, t0 + 121_000, esc)).toBe('danger')
  })
})
