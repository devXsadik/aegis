import { describe, expect, it } from 'vitest'
import { can, canViewPage } from './permissions'

describe('canViewPage', () => {
  it('lets supervisors and admins open every page', () => {
    for (const role of ['admin', 'supervisor']) expect(canViewPage(role, 'users')).toBe(true)
  })
  it('keeps roles to their pages, and unknown roles out', () => {
    expect(canViewPage('viewer', 'live')).toBe(true)
    expect(canViewPage('viewer', 'evidence')).toBe(false)
    expect(canViewPage('police', 'cameras')).toBe(false)
    expect(canViewPage(undefined, 'overview')).toBe(false)
    expect(canViewPage('intern', 'overview')).toBe(false)
  })
  it('opens a merged page when the role may open either of its views', () => {
    expect(canViewPage('operator', 'faces')).toBe(true)         // registry only
    expect(canViewPage('operator', 'watchlist')).toBe(false)
    expect(canViewPage('investigator', 'analytics')).toBe(true) // trends only
    expect(canViewPage('investigator', 'detection')).toBe(false)
    expect(canViewPage('police', 'analytics')).toBe(false)
  })
})

describe('can', () => {
  it('matches the backend role sets', () => {
    expect(can('viewer', 'data.view')).toBe(true)      // a wall display reads the live picture ...
    expect(can('viewer', 'media.view')).toBe(false)    // ... but not stills, recordings or person searches
    expect(can('police', 'media.view')).toBe(true)
    expect(can('police', 'data.view')).toBe(true)
    expect(can('supervisor', 'audit.view')).toBe(false)
    expect(can('admin', 'audit.view')).toBe(true)
    expect(can(null, 'triage.act')).toBe(false)
  })
})
