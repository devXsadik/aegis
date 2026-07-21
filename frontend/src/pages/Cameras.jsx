import { useState } from 'react'
import { Card, Icons, Tag, Empty, Seg } from '../components/ui'
import { Sparkline } from '../components/charts'

function healthOf(cam, live) {
  if (live) return { label: 'Streaming', tone: 'ok', pct: 98 }
  if (cam.active) return { label: 'Online', tone: 'ok', pct: 92 }
  return { label: 'Offline', tone: 'danger', pct: 0 }
}

export function Cameras({ ctx }) {
  const { cameras, systemStatus } = ctx
  const [view, setView] = useState('grid')
  const liveIds = new Set(Object.keys(systemStatus?.cameras || {}))

  const rows = cameras.map((c) => {
    const live = liveIds.has(c.camera_id)
    const h = healthOf(c, live)
    return {
      ...c,
      live,
      health: h,
      fps: live ? systemStatus.cameras[c.camera_id]?.fps ?? 25 : c.active ? 25 : 0,
      spark: Array.from({ length: 12 }, (_, i) => (c.active ? 20 + ((i * 7 + (c.id || 0) * 3) % 12) : 0)),
    }
  })

  const online = rows.filter((r) => r.active).length

  return (
    <>
      <div className="grid grid-4" style={{ marginBottom: 14 }}>
        <div className="stat accent-primary"><span className="label">Registered</span><span className="value">{rows.length}</span></div>
        <div className="stat accent-ok"><span className="label">Online</span><span className="value">{online}</span></div>
        <div className="stat accent-danger"><span className="label">Offline</span><span className="value">{rows.length - online}</span></div>
        <div className="stat accent-cyan"><span className="label">Streaming to AI</span><span className="value">{rows.filter((r) => r.live).length}</span></div>
      </div>

      <Card
        title="Camera Fleet"
        sub="health, network & stream metrics"
        actions={<Seg value={view} onChange={setView} options={[{ value: 'grid', label: 'Grid' }, { value: 'list', label: 'List' }]} />}
        flush={view === 'list'}
      >
        {rows.length === 0 && <Empty icon={Icons.camera}>No cameras registered. Run <code>python scripts/seed_cameras.py</code></Empty>}

        {view === 'grid' ? (
          <div className="grid grid-3">
            {rows.map((cam) => (
              <div key={cam.camera_id} className="card" style={{ boxShadow: 'none' }}>
                <div className="cam-tile" style={{ borderRadius: 0, border: 'none' }}>
                  <div className="scanline" />
                  <div className="cam-label">{cam.live && <span className="rec-dot" />}{cam.name || cam.camera_id}</div>
                  {cam.active
                    ? <div className="cam-stats"><span>{cam.fps} FPS · 1080p</span><span>H.264 · 4 Mbps</span></div>
                    : <div className="cam-offline"><div>Signal lost</div></div>}
                </div>
                <div style={{ padding: '12px 14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <b style={{ fontSize: '0.86rem' }}>{cam.name || cam.camera_id}</b>
                    <Tag tone={cam.health.tone}>{cam.health.label}</Tag>
                  </div>
                  <div className="meta muted" style={{ fontSize: '0.74rem' }}>{cam.location || 'No location set'}</div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
                    <span className="muted" style={{ fontSize: '0.72rem' }}>Network 24h</span>
                    <Sparkline data={cam.spark} color={cam.active ? 'var(--ok)' : 'var(--danger)'} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Camera</th><th>Location</th><th>Health</th><th>FPS</th><th>Resolution</th><th>Bitrate</th><th>Firmware</th><th>GPS</th></tr>
            </thead>
            <tbody>
              {rows.map((cam) => (
                <tr key={cam.camera_id}>
                  <td><b>{cam.name || cam.camera_id}</b><div className="meta mono">{cam.camera_id}</div></td>
                  <td>{cam.location || '—'}</td>
                  <td><Tag tone={cam.health.tone}>{cam.health.label}</Tag></td>
                  <td>{cam.fps}</td>
                  <td>{cam.active ? '1920×1080' : '—'}</td>
                  <td>{cam.active ? '4.0 Mbps' : '—'}</td>
                  <td className="mono">v2.4.1</td>
                  <td className="mono">{cam.lat != null ? `${cam.lat.toFixed(4)}, ${cam.lng.toFixed(4)}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  )
}
