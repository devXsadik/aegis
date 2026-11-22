import { describe, expect, it } from 'vitest'
import { buildCamList, cameraForDevice, slug } from './cameras'
import { parseTs } from './time'

describe('cameraForDevice', () => {
  it('picks a free id bound to the device', () => {
    const cams = [{ camera_id: 'facetime_hd_camera' }]
    expect(cameraForDevice({ name: 'FaceTime HD Camera', source: 'device:abc' }, cams))
      .toEqual({ camera_id: 'facetime_hd_camera_2', name: 'FaceTime HD Camera', location: 'Local', rtsp_url: 'device:abc' })
    expect(slug('  ')).toBe('')
  })
})

describe('buildCamList', () => {
  const cameras = [
    { camera_id: 'gate', name: 'Gate', active: true },
    { camera_id: 'lab', name: 'Lab', active: true },
    { camera_id: 'cam_0', name: 'Placeholder', active: true },
    { camera_id: 'usb', name: 'USB', active: true },
  ]
  it('derives live / no video / off / offline and puts live first', () => {
    const status = { cameras: { lab: { fps: 7.6, threat_score: 45, flags: [{ type: 'CRIMINAL_DETECTED' }] }, gate: { fps: 8 } } }
    const list = buildCamList(cameras, status, ['lab'], { gate: false }, ['usb'])
    expect(list.map((c) => [c.camera_id, c.status])).toEqual([['lab', 'live'], ['gate', 'off']])
    expect(list[0]).toMatchObject({ fps: 7.6, threat_score: 45 })
    expect(list[0].flags).toHaveLength(1)
  })
  it('lists a camera that reports but is not registered', () => {
    const list = buildCamList([], { cameras: { phone: { camera_location: 'Phone' } } })
    expect(list).toEqual([expect.objectContaining({ camera_id: 'phone', name: 'Phone', status: 'online' })])
  })
})

describe('parseTs', () => {
  it('reads zone-less backend timestamps as UTC', () => {
    expect(parseTs('2026-11-22T12:00:00').toISOString()).toBe('2026-11-22T12:00:00.000Z')
    expect(parseTs('2026-11-22T12:00:00+06:00').toISOString()).toBe('2026-11-22T06:00:00.000Z')
    expect(parseTs('')).toBeNull()
    expect(parseTs('nonsense')).toBeNull()
  })
})
