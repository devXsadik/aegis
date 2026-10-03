import { useState } from 'react'
import { Card, Icons, Tag, Empty, timeAgo, SEVERITY_TONE, Seg } from '../components/ui'
import { acknowledgeAlert, dispatchPolice, createIncidentFromAlert } from '../services/api'
import { useToast } from '../components/Toast'

const PRIORITY_ORDER = { critical: 0, high: 1, medium: 2, info: 3, low: 4 }

export function AlertCenter({ ctx }) {
  const { events, setEvents, setPage } = ctx
  const { push: toast } = useToast()
  const [filter, setFilter] = useState('all')
  const [handled, setHandled] = useState({})

  const filtered = events
    .filter((e) => filter === 'all' || e.severity === filter)
    .sort((a, b) => (PRIORITY_ORDER[a.severity] ?? 5) - (PRIORITY_ORDER[b.severity] ?? 5))

  /* Persist to backend when the alert has a DB id; always update the UI */
  const mark = async (key, status, evt) => {
    setHandled((h) => ({ ...h, [key]: status }))
    if (evt?.id == null) return
    try {
      if (status === 'dispatched') {
        await dispatchPolice(evt.id)
      } else {
        await acknowledgeAlert(evt.id, {
          acknowledged: status === 'verified',
          dismissed: status === 'dismissed',
        })
      }
      setEvents?.((prev) => prev.map((e) => (
        e.id === evt.id
          ? { ...e, acknowledged: status !== 'dismissed', dismissed: status === 'dismissed' }
          : e
      )))
    } catch (err) {
      toast(err.message || 'Action failed', 'danger')
    }
  }

  const openIncident = async (evt) => {
    if (!evt?.id) { toast('Save alert to DB before creating incident', 'danger'); return }
    try {
      await createIncidentFromAlert(evt.id)
      toast('Incident created from alert', 'ok')
      setPage?.('incidents')
    } catch (err) {
      toast(err.message || 'Failed to create incident', 'danger')
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Alert Center</h2>
          <p>Priority queue for verification, dispatch, and dismissal.</p>
        </div>
        <div className="head-actions">
          <Seg
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: 'All' },
              { value: 'critical', label: 'Critical' },
              { value: 'high', label: 'High' },
              { value: 'medium', label: 'Medium' },
              { value: 'info', label: 'Info' },
            ]}
          />
        </div>
      </div>

    <Card
      title="Active queue"
      sub={`${filtered.length} alerts · sorted by priority`}
    >
      {filtered.length === 0 && <Empty icon={Icons.bell}>No alerts match this filter</Empty>}
      <div className="grid grid-2">
        {filtered.map((evt, i) => {
          const key = evt.id != null ? `alert-${evt.id}` : `${evt.type}-${evt.time}-${i}`
          const status = handled[key] || (evt.dismissed ? 'dismissed' : evt.acknowledged ? 'verified' : null)
          return (
            <div key={key} className={`alert-card p-${evt.severity || 'info'}`} style={status === 'dismissed' ? { opacity: 0.45 } : undefined}>
              <div className="a-top">
                <span className="a-thumb" style={{ background: 'var(--surface-2)' }}>
                  {evt.severity === 'critical' ? '🚨' : evt.severity === 'high' ? '⚠️' : '🔔'}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div className="a-title">{evt.type?.replace(/_/g, ' ')}</div>
                  <div className="a-meta">
                    <span>{evt.camera || 'Unknown camera'}</span>
                    <span>{timeAgo(evt.time)}</span>
                    {evt.lat != null && <span className="mono">{Number(evt.lat).toFixed(4)}, {Number(evt.lng).toFixed(4)}</span>}
                  </div>
                </div>
                <span className="spacer" />
                <Tag tone={SEVERITY_TONE[evt.severity] || 'muted'}>{evt.severity}</Tag>
              </div>
              <div style={{ fontSize: '0.84rem', color: 'var(--text-2)' }}>{evt.msg}</div>
              <div className="a-actions">
                {status === 'verified' && <Tag tone="ok">Verified</Tag>}
                {status === 'dispatched' && <Tag tone="info">Police dispatched</Tag>}
                {status === 'dismissed' && <Tag tone="muted">Dismissed</Tag>}
                {!status && (
                  <>
                    <button className="btn btn-sm" onClick={() => mark(key, 'verified', evt)}><Icons.check /> Verify</button>
                    <button className="btn btn-sm btn-primary" onClick={() => mark(key, 'dispatched', evt)}><Icons.dispatch /> Dispatch Police</button>
                    <button className="btn btn-sm" onClick={() => openIncident(evt)}>Create Incident</button>
                    {evt.mapsUrl && (
                      <a className="btn btn-sm" href={evt.mapsUrl} target="_blank" rel="noreferrer"><Icons.map /> Open Map</a>
                    )}
                    <button className="btn btn-sm btn-ghost" onClick={() => mark(key, 'dismissed', evt)}>Dismiss</button>
                  </>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </Card>
    </>
  )
}

