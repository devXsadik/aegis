/* Incident detail drawer: snapshot, map, status, officers, typed activity timeline, notes. */
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icons, timeAgo, useDialog } from './ui'
import { AlertTypeBadge, DsIcons, EmptyState, ErrorState, SeverityBadge, Skeleton } from './ds'
import { StatusSelector } from './StatusSelector'
import { OfficerChip, OfficerPicker } from './Officers'
import { EvidenceGallery } from './EvidenceGallery'
import { EvidenceUploader } from './EvidenceUploader'
import { parseTs } from '../lib/time'
import { can } from '../lib/permissions'
import { downloadEvidencePackage, fetchJurisdictions } from '../services/api'

const IncidentMap = lazy(() => import('./IncidentMap'))

const KIND = {
  CREATED: { icon: Icons.plus, tone: 'info', label: 'Created' },
  ALERT: { icon: Icons.alert, tone: 'warn', label: 'Alert' },
  MATCHED: { icon: Icons.watchlist, tone: 'purple', label: 'Matched' },
  VERIFIED: { icon: Icons.shield, tone: 'purple', label: 'Verified' },
  STATUS: { icon: DsIcons.refresh, tone: 'info', label: 'Status' },
  PRIORITY: { icon: Icons.alert, tone: 'orange', label: 'Severity' },
  ASSIGNED: { icon: Icons.users, tone: 'cyan', label: 'Assigned' },
  UNASSIGNED: { icon: Icons.users, tone: 'muted', label: 'Removed' },
  OFFICER_STATE: { icon: Icons.dispatch, tone: 'cyan', label: 'Officer' },
  NOTE: { icon: Icons.report, tone: 'muted', label: 'Note' },
  HANDOFF: { icon: Icons.camera, tone: 'orange', label: 'Camera handoff' },
  EVIDENCE: { icon: Icons.evidence, tone: 'info', label: 'Evidence' },
  OVERRIDE: { icon: DsIcons.lock, tone: 'warn', label: 'Override' },
  BOLO: { icon: Icons.eye, tone: 'orange', label: 'Lookout' },
  NOTIFIED: { icon: Icons.bell, tone: 'muted', label: 'Notified' },
}

const fmt = (ts) => parseTs(ts)?.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) || ''

export function Timeline({ events }) {
  if (!events?.length) return <EmptyState compact icon={Icons.clock}>No activity yet</EmptyState>
  return (
    <ol className="tl">
      {[...events].reverse().map((ev) => {
        const k = KIND[ev.event_type] || { icon: DsIcons.dot, tone: 'muted', label: ev.event_type }
        const Icon = k.icon
        return (
          <li key={ev.id} className={`tl-item tone-${k.tone}`}>
            <span className="tl-icon"><Icon aria-hidden="true" /></span>
            <div className="tl-body">
              <div className="tl-head"><b>{k.label}</b><time dateTime={ev.created_at} title={fmt(ev.created_at)}>{timeAgo(ev.created_at)}</time></div>
              <div className="tl-msg">{ev.message}</div>
              <div className="tl-who">{ev.actor || 'SYSTEM'}{ev.camera_id ? ` · camera ${ev.camera_id}` : ''}</div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

let areasCache = null

export function IncidentDrawer({ incident, loading, error, onRetry, spec, me, onClose, onStatus, onAssign, onUnassign, onNote, toast }) {
  const ref = useRef(null)
  useDialog(ref, onClose)
  const [picker, setPicker] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [evReload, setEvReload] = useState(0)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [areas, setAreas] = useState(areasCache)
  const role = me?.role
  const canEdit = can(role, 'incident.edit')
  const canAssign = ['operator', 'supervisor', 'admin'].includes(role)
  const canOverride = ['supervisor', 'admin'].includes(role)

  useEffect(() => {
    if (areasCache) return
    fetchJurisdictions().then((a) => { areasCache = a; setAreas(a) }).catch(() => {})
  }, [])
  const area = incident && areas?.find((a) => a.id === incident.jurisdiction_id)

  const saveNote = async () => {
    setSaving(true)
    try { if (await onNote(note.trim())) setNote('') } finally { setSaving(false) }
  }

  // Portalled to <body>: inside the page's animated container a fixed sheet is clipped to the page's height.
  return createPortal(
    <div className="drawer-scrim" onClick={onClose}>
      <aside ref={ref} className="drawer inc-drawer" role="dialog" aria-modal="true" aria-labelledby="inc-drawer-title"
        onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <div className="inc-drawer-title">
            <span className="mono muted">{incident?.ticket_id || '…'}</span>
            <h2 id="inc-drawer-title">{incident?.title || 'Loading incident'}</h2>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close details"><Icons.close /></button>
        </header>

        {error && <ErrorState message={error} onRetry={onRetry} />}
        {!error && (loading || !incident) && (
          <div className="drawer-body" style={{ display: 'grid', gap: 14 }}>
            <Skeleton h={180} r={14} /><Skeleton h={18} w="60%" /><Skeleton h={120} r={14} />
          </div>
        )}
        {!error && incident && !loading && (
          <div className="drawer-body">
            <div className="inc-drawer-bar">
              <StatusSelector spec={spec} value={incident.status} role={role} disabled={!canEdit}
                onChange={(s, n) => onStatus(incident, s, n)} />
              <SeverityBadge level={incident.priority} />
              <AlertTypeBadge type={incident.incident_type} />
              {canAssign && (
                <button type="button" className="btn btn-sm btn-primary inc-assign-top" onClick={() => setPicker(true)}>
                  <Icons.dispatch /> {incident.assignments.length ? 'Assign more officers' : 'Assign officers'}
                </button>
              )}
            </div>

            <div className="inc-media">
              {incident.snapshot
                ? <img src={incident.snapshot.url} alt={`Snapshot from ${incident.camera_location || 'camera'}`} />
                : <EmptyState compact icon={Icons.camera}>No snapshot for this incident</EmptyState>}
              <Suspense fallback={<Skeleton h={220} r={14} />}>
                <IncidentMap lat={incident.lat} lng={incident.lng} area={area} label={incident.camera_location} trail={incident.trail} />
              </Suspense>
            </div>

            <dl className="inc-detail-grid">
              <div><dt>Camera</dt><dd>{incident.camera_location || '—'}{incident.camera_id && <span className="muted mono"> · {incident.camera_id}</span>}</dd></div>
              <div><dt>Jurisdiction</dt><dd>{area ? `${area.name_en}${area.name_bn ? ` · ${area.name_bn}` : ''}` : <span className="muted">Not recorded</span>}</dd></div>
              <div><dt>Opened</dt><dd title={fmt(incident.created_at)}>{timeAgo(incident.created_at)} · {incident.created_by_name || 'SYSTEM'}</dd></div>
              <div><dt>Case owner</dt><dd>{incident.assigned_name || <span className="muted">Nobody yet</span>}</dd></div>
              {incident.person_name && <div><dt>Subject</dt><dd><Icons.watchlist /> {incident.person_name}</dd></div>}
              {incident.plate_number && <div><dt>Plate</dt><dd className="mono">{incident.plate_number}</dd></div>}
              {incident.lat != null && <div><dt>GPS</dt><dd className="mono">{Number(incident.lat).toFixed(5)}, {Number(incident.lng).toFixed(5)}</dd></div>}
            </dl>
            {incident.description && incident.description !== incident.title && <p className="inc-desc">{incident.description}</p>}

            <section className="inc-sec" aria-labelledby="inc-off-h">
              <div className="inc-sec-head">
                <h3 id="inc-off-h" className="inc-section-title">Officers ({incident.assignments.length})</h3>
                {canAssign && <button type="button" className="btn btn-sm btn-primary" onClick={() => setPicker(true)}><Icons.plus /> Assign</button>}
              </div>
              {incident.assignments.length === 0
                ? <EmptyState compact icon={Icons.users} title="No officer assigned"
                    action={canAssign && <button type="button" className="btn btn-sm" onClick={() => setPicker(true)}>Find officers in this jurisdiction</button>}>
                    Officers whose jurisdiction covers this camera are listed first.
                  </EmptyState>
                : <div className="off-chips">{incident.assignments.map((a) => (
                    <OfficerChip key={a.user_id} a={a} onRemove={canAssign ? (x) => onUnassign(incident, x) : null} />
                  ))}</div>}
            </section>

            <section className="inc-sec" aria-labelledby="inc-ev-h">
              <div className="inc-sec-head">
                <h3 id="inc-ev-h" className="inc-section-title">Evidence</h3>
                {canEdit && <button type="button" className="btn btn-sm" onClick={() => setUploading((u) => !u)}><Icons.plus /> {uploading ? 'Close upload' : 'Add evidence'}</button>}
              </div>
              {uploading && <EvidenceUploader incidentId={incident.id} onUploaded={() => setEvReload((n) => n + 1)} />}
              <EvidenceGallery me={me} incidentId={incident.id} reloadKey={evReload} />
            </section>

            <section className="inc-sec" aria-labelledby="inc-tl-h">
              <h3 id="inc-tl-h" className="inc-section-title">Activity</h3>
              <Timeline events={incident.events} />
            </section>

            <section className="inc-sec" aria-labelledby="inc-notes-h">
              <h3 id="inc-notes-h" className="inc-section-title">Notes ({incident.notes.length})</h3>
              {incident.notes.map((n) => (
                <div key={n.id} className="inc-note">
                  <div className="tl-head"><b>{n.author_name}</b><time dateTime={n.created_at}>{timeAgo(n.created_at)}</time></div>
                  <p>{n.body}</p>
                </div>
              ))}
              {canEdit && (
                <div className="inc-note-form">
                  <label className="sr-only" htmlFor="inc-note">Add note</label>
                  <textarea id="inc-note" className="input" rows={2} value={note} maxLength={5000}
                    onChange={(e) => setNote(e.target.value)} placeholder="What did you find?" />
                  <button type="button" className="btn btn-sm btn-primary" onClick={saveNote} disabled={!note.trim() || saving}>
                    {saving ? 'Saving…' : 'Add note'}
                  </button>
                </div>
              )}
            </section>
          </div>
        )}

        {incident && !loading && (
          <footer className="drawer-foot">
            <button type="button" className="btn btn-sm" onClick={() => window.print()}><Icons.report /> Print</button>
            <button type="button" className="btn btn-sm" onClick={() => { downloadEvidencePackage(incident.id); toast('Building the evidence package: the download starts in a moment', 'ok') }}>
              <Icons.download /> Evidence package
            </button>
          </footer>
        )}
        {picker && incident && createPortal(
          <div className="layer-top" onClick={(e) => e.stopPropagation()}>
            <OfficerPicker incident={incident} canOverride={canOverride} onClose={() => setPicker(false)}
              onAssign={(ids, opts) => onAssign(incident, ids, opts)} />
          </div>, document.body)}
      </aside>
    </div>,
    document.body,
  )
}
