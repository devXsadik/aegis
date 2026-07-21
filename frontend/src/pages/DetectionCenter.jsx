import { useState } from 'react'
import { Card, Icons, Tag, Empty, timeAgo, SEVERITY_TONE, Seg } from '../components/ui'

const PANELS = [
  { id: 'all', label: 'All' },
  { id: 'face', label: 'Face Recognition', match: (e) => /CRIMINAL|FACE|PERSON/i.test(e.type) },
  { id: 'weapon', label: 'Weapon', match: (e) => /WEAPON|KNIFE|GUN/i.test(e.type) },
  { id: 'vehicle', label: 'Vehicle / ANPR', match: (e) => /VEHICLE|PLATE|ANPR/i.test(e.type) },
  { id: 'behavior', label: 'Behavior', match: (e) => /LOITER|INTRUSION|VIOLEN|SUSPICIOUS|CROWD/i.test(e.type) },
  { id: 'fire', label: 'Fire / Smoke', match: (e) => /FIRE|SMOKE/i.test(e.type) },
]

const TYPE_ICON = (type = '') => {
  if (/WEAPON|KNIFE|GUN/i.test(type)) return '🔫'
  if (/CRIMINAL|FACE/i.test(type)) return '🎭'
  if (/VEHICLE|PLATE/i.test(type)) return '🚗'
  if (/FIRE|SMOKE/i.test(type)) return '🔥'
  if (/LOITER|INTRUSION|SUSPICIOUS/i.test(type)) return '👁'
  return '📡'
}

export function DetectionCenter({ ctx }) {
  const { events } = ctx
  const [panel, setPanel] = useState('all')

  const active = PANELS.find((p) => p.id === panel)
  const filtered = panel === 'all' ? events : events.filter((e) => active.match?.(e))

  const counts = PANELS.slice(1).map((p) => ({ ...p, count: events.filter((e) => p.match?.(e)).length }))

  return (
    <>
      <div className="grid grid-4" style={{ gridTemplateColumns: 'repeat(5, 1fr)', marginBottom: 14 }}>
        {counts.map((p) => (
          <div key={p.id} className="stat accent-primary" style={{ cursor: 'pointer' }} onClick={() => setPanel(p.id)}>
            <span className="label">{p.label}</span>
            <span className="value">{p.count}</span>
            <span className="delta">this session</span>
          </div>
        ))}
      </div>

      <Card
        title="AI Detection Feed"
        sub={`${filtered.length} detections`}
        actions={<Seg value={panel} onChange={setPanel} options={PANELS.map((p) => ({ value: p.id, label: p.label }))} />}
      >
        {filtered.length === 0 && (
          <Empty icon={Icons.ai}>
            No {panel === 'all' ? '' : `${active.label.toLowerCase()} `}detections yet.
            Start the pipeline: <code>./scripts/run_defense_demo.sh</code>
          </Empty>
        )}
        <div className="grid grid-2">
          {filtered.slice(0, 20).map((evt, i) => (
            <div key={i} className={`alert-card p-${evt.severity || 'info'}`}>
              <div className="a-top">
                <span className="a-thumb" style={{ background: 'var(--surface-2)' }}>{TYPE_ICON(evt.type)}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="a-title">{evt.type?.replace(/_/g, ' ')}</div>
                  <div className="a-meta">
                    <span>{evt.camera || 'Unknown camera'}</span>
                    <span>{timeAgo(evt.time)}</span>
                    {evt.personName && <span>ID: {evt.personName}</span>}
                  </div>
                </div>
                <span className="spacer" />
                <Tag tone={SEVERITY_TONE[evt.severity] || 'muted'}>{evt.severity}</Tag>
              </div>
              <div style={{ fontSize: '0.83rem', color: 'var(--text-2)' }}>{evt.msg}</div>
              {evt.lat != null && (
                <div className="mono muted">📍 {Number(evt.lat).toFixed(5)}, {Number(evt.lng).toFixed(5)}</div>
              )}
            </div>
          ))}
        </div>
      </Card>
    </>
  )
}
