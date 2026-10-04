import { useEffect, useState } from 'react'
import { Card, Icons, Tag, Empty, timeAgo } from '../components/ui'
import { fetchReidPersons, personImageUrl } from '../services/api'
import { EnrollModal, ManagePersonModal, VerifyPanel } from '../components/FaceRegistry'

const THREAT_TONE = (lvl) => (lvl >= 4 ? 'danger' : lvl >= 2 ? 'warn' : 'ok')

export function Watchlist({ ctx }) {
  const { knownPersons, reloadKnownPersons, events, evidence, me } = ctx
  const [reid, setReid] = useState([])
  const [enrolling, setEnrolling] = useState(false)
  const [managing, setManaging] = useState(null)
  const canEdit = me?.role === 'admin' || me?.role === 'supervisor'
  const canDelete = me?.role === 'admin'

  useEffect(() => {
    fetchReidPersons(72).then((r) => setReid(r.persons || [])).catch(() => {})
  }, [evidence.length])

  const lastSeen = (p) => {
    const hit = events.find((e) => e.personName === p.name)
      || evidence.find((ev) => ev.person_name === p.name)
    return hit ? (hit.time || hit.timestamp) : null
  }

  const detections = (p) =>
    events.filter((e) => e.personName === p.name).length +
    evidence.filter((ev) => ev.person_name === p.name).length

  return (
    <>
      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <div className="stat accent-danger"><span className="label">Watchlisted Persons</span><span className="value">{knownPersons.length}</span></div>
        <div className="stat accent-warn"><span className="label">Wanted / Suspects</span><span className="value">{knownPersons.filter((p) => ['wanted', 'suspect'].includes(p.criminal_status)).length}</span></div>
        <div className="stat accent-primary"><span className="label">Cross-camera tracks</span><span className="value">{reid.filter((t) => t.cross_camera).length}</span></div>
      </div>

      <div className="grid grid-2" style={{ marginBottom: 14, alignItems: 'start' }}>
        <VerifyPanel persons={knownPersons} />
        <Card title="Face records" sub="enrolled photos are matched live by every camera"
          actions={canEdit && <button className="btn btn-primary btn-sm" onClick={() => setEnrolling(true)}>+ Enroll face</button>}>
          <div className="meta">
            {knownPersons.length} record(s) · {knownPersons.reduce((n, p) => n + (p.encoding_count || 0), 0)} embeddings.
            {canEdit ? ' Upload clear, front-facing photos; add several angles per person.' : ' Supervisor or admin access is required to enroll faces.'}
          </div>
        </Card>
      </div>

      {knownPersons.length === 0 ? (
        <Card><Empty icon={Icons.watchlist}>No face records yet. {canEdit ? 'Use “Enroll face” to add one.' : 'Ask a supervisor to enroll faces.'}</Empty></Card>
      ) : (
        <div className="grid grid-3" style={{ marginBottom: 14 }}>
          {knownPersons.map((p) => {
            const seen = lastSeen(p)
            const count = detections(p)
            return (
              <Card key={p.id}>
                <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginBottom: 12 }}>
                  {p.first_image_id ? (
                    <img src={personImageUrl(p.first_image_id)} alt={p.name}
                      style={{ width: 52, height: 52, borderRadius: '50%', objectFit: 'cover' }} />
                  ) : (
                    <div className="avatar" style={{ width: 52, height: 52, fontSize: '1.2rem', background: 'linear-gradient(135deg,#3b82f6,#7c3aed)' }}>
                      {p.name?.[0]?.toUpperCase() || '?'}
                    </div>
                  )}
                  <div style={{ minWidth: 0 }}>
                    <b style={{ fontSize: '0.95rem' }}>{p.name}</b>
                    <div className="meta mono">{p.person_id}</div>
                  </div>
                  <span className="spacer" />
                  <Tag tone={['wanted', 'convicted', 'suspect'].includes(p.criminal_status) ? 'danger' : 'ok'}>{p.criminal_status}</Tag>
                </div>
                <dl className="kv">
                  <dt>Category</dt><dd>{p.category || '—'}</dd>
                  <dt>Risk Level</dt><dd><Tag tone={THREAT_TONE(p.threat_level)}>Level {p.threat_level}</Tag></dd>
                  <dt>Last Seen</dt><dd>{seen ? timeAgo(seen) : 'Not seen this session'}</dd>
                  <dt>Detections</dt><dd>{count}</dd>
                  <dt>Photos</dt><dd>{p.image_count} · {p.encoding_count} embeddings</dd>
                </dl>
                <button className="btn btn-sm" style={{ marginTop: 10 }} onClick={() => setManaging(p)}>
                  {canEdit ? 'Manage' : 'View'}
                </button>
              </Card>
            )
          })}
        </div>
      )}

      {enrolling && <EnrollModal onClose={() => setEnrolling(false)} onDone={reloadKnownPersons} />}
      {managing && (
        <ManagePersonModal person={managing} canEdit={canEdit} canDelete={canDelete}
          onClose={() => setManaging(null)} onChanged={reloadKnownPersons} />
      )}

      <Card title="Cross-Camera Re-ID" sub="same identity across cameras · last 72h">
        {reid.length === 0 && <Empty icon={Icons.map}>No multi-camera identity tracks yet</Empty>}
        {reid.slice(0, 15).map((t) => (
          <div key={t.person_name} className="row">
            <div>
              <b>{t.person_name}</b>
              <div className="meta">{t.sightings} sightings · {t.cameras.join(' → ')}</div>
            </div>
            <Tag tone={t.cross_camera ? 'info' : 'muted'}>{t.cross_camera ? 'Multi-cam' : 'Single'}</Tag>
          </div>
        ))}
      </Card>
    </>
  )
}
