/* eslint-disable react-refresh/only-export-components */
/* Officer avatar / chips and the jurisdiction-based officer picker.
   The list comes from GET /incidents/{id}/eligible-officers: the server decides who covers the
   camera; this only shows it. Neighbouring areas: supervisor/admin only, and logged. */
import { useEffect, useMemo, useState } from 'react'
import { Icons, Modal } from './ui'
import { Badge, EmptyState, ErrorState, SkeletonList } from './ds'
import { fetchEligibleOfficers, officerPhotoUrl } from '../services/api'

export const DUTY = {
  available: { label: 'Available', tone: 'ok' },
  on_duty: { label: 'On duty', tone: 'info' },
  busy: { label: 'Busy', tone: 'warn' },
  off_duty: { label: 'Off duty', tone: 'muted' },
}

const initials = (name) => (name || '?').split(/[\s_]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()

export function OfficerAvatar({ id, name, hasPhoto, size = 32, ring }) {
  const [failed, setFailed] = useState(false)
  const style = { width: size, height: size, fontSize: Math.max(10, size * 0.38) }
  return (
    <span className={`off-avatar ${ring ? `ring-${ring}` : ''}`} style={style} title={name} aria-hidden="true">
      {hasPhoto && !failed
        ? <img src={officerPhotoUrl(id)} alt="" loading="lazy" onError={() => setFailed(true)} />
        : initials(name)}
    </span>
  )
}

/** Overlapping avatars for a table cell. */
export function OfficerStack({ assignments = [], max = 3 }) {
  if (!assignments.length) return <span className="muted">—</span>
  const shown = assignments.slice(0, max)
  const names = assignments.map((a) => a.name).join(', ')
  return (
    <span className="off-stack" aria-label={`Officers: ${names}`} title={names}>
      {shown.map((a) => <OfficerAvatar key={a.user_id} id={a.user_id} name={a.name} hasPhoto={a.has_photo} size={28} />)}
      {assignments.length > max && <span className="off-more">+{assignments.length - max}</span>}
    </span>
  )
}

const STATE_LABEL = { assigned: 'Assigned', acknowledged: 'Acknowledged', en_route: 'En route', on_scene: 'On scene', located: 'Located target', unable: 'Unable' }
const STATE_TONE = { assigned: 'muted', acknowledged: 'info', en_route: 'cyan', on_scene: 'warn', located: 'ok', unable: 'danger' }

/** Removable chip for an assigned officer. */
export function OfficerChip({ a, onRemove }) {
  return (
    <span className="off-chip">
      <OfficerAvatar id={a.user_id} name={a.name} hasPhoto={a.has_photo} size={30} />
      <span className="off-chip-text">
        <b>{a.rank ? `${a.rank} ` : ''}{a.name}</b>
        <span>
          <Badge tone={STATE_TONE[a.state] || 'muted'} size="sm">{STATE_LABEL[a.state] || a.state}</Badge>
          {a.out_of_area && <Badge tone="warn" size="sm" title="Assigned from a neighbouring jurisdiction">Out of area</Badge>}
        </span>
      </span>
      {onRemove && (
        <button type="button" className="icon-btn off-chip-x" aria-label={`Remove ${a.name}`} onClick={() => onRemove(a)}>
          <Icons.close />
        </button>
      )}
    </span>
  )
}

const km = (m) => (m == null ? null : m < 1000 ? `${m} m` : `${(m / 1000).toFixed(1)} km`)

function OfficerCard({ o, selected, onToggle }) {
  const duty = DUTY[o.duty_status] || DUTY.off_duty
  return (
    <li>
      <label className={`off-card ${selected ? 'selected' : ''} ${o.assigned ? 'is-assigned' : ''}`}>
        <input type="checkbox" checked={selected || o.assigned} disabled={o.assigned} onChange={() => onToggle(o.id)}
          aria-label={`Select ${o.name}`} />
        <OfficerAvatar id={o.id} name={o.name} hasPhoto={o.has_photo} size={48} ring={duty.tone} />
        <span className="off-card-main">
          <span className="off-card-name"><b>{o.name}</b>{o.rank && <span className="muted"> · {o.rank}</span>}</span>
          <span className="off-card-meta">
            {o.badge_no && <span className="mono">#{o.badge_no}</span>}
            {o.station && <span><Icons.shield /> {o.station}</span>}
            {o.phone && <a href={`tel:${o.phone}`} onClick={(e) => e.stopPropagation()} className="mono">{o.phone}</a>}
          </span>
          <span className="off-card-tags">
            <Badge tone={duty.tone} size="sm">{duty.label}</Badge>
            <Badge tone={o.active_incidents ? 'warn' : 'muted'} size="sm" icon={Icons.incident}>{o.active_incidents} active</Badge>
            {km(o.distance_m) && <Badge tone="muted" size="sm" icon={Icons.map}>{km(o.distance_m)}</Badge>}
            {o.out_of_area && <Badge tone="warn" size="sm">Neighbouring area</Badge>}
            {o.assigned && <Badge tone="info" size="sm" icon={Icons.check}>Already assigned</Badge>}
          </span>
        </span>
      </label>
    </li>
  )
}

export function OfficerPicker({ incident, canOverride, onClose, onAssign }) {
  const [neighbours, setNeighbours] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState([])
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [loadedKey, setLoadedKey] = useState(null)
  const key = `${neighbours}-${attempt}`
  const loading = loadedKey !== key

  useEffect(() => {
    let off = false
    fetchEligibleOfficers(incident.id, neighbours)
      .then((d) => { if (!off) { setData(d); setError('') } })
      .catch((e) => { if (!off) setError(e.message || 'Could not load officers') })
      .finally(() => { if (!off) setLoadedKey(key) })
    return () => { off = true }
  }, [incident.id, neighbours, key])

  const list = useMemo(() => {
    const s = q.trim().toLowerCase()
    return (data?.officers || []).filter((o) => !s || [o.name, o.rank, o.badge_no, o.station, o.phone]
      .some((v) => v && String(v).toLowerCase().includes(s)))
  }, [data, q])
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const pickedOut = (data?.officers || []).filter((o) => picked.includes(o.id) && o.out_of_area)
  const needReason = pickedOut.length > 0

  const submit = async () => {
    setBusy(true)
    try {
      const ids = picked.filter((id) => (data?.officers || []).some((o) => o.id === id))
      await onAssign(ids, { includeNeighbours: neighbours, reason })
      onClose()
    } catch {
      /* the page already showed the error; keep the picker open */
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal className="off-picker" title={`Assign officers — ${incident.ticket_id}`} onClose={onClose}
      footer={(
        <div className="off-picker-foot">
          <span className="muted">{picked.length ? `${picked.length} selected` : 'Pick one or more officers'}</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button type="button" className="btn btn-primary" disabled={!picked.length || busy || (needReason && reason.trim().length < 3)} onClick={submit}>
              {busy ? 'Assigning…' : `Assign${picked.length ? ` ${picked.length}` : ''}`}
            </button>
          </div>
        </div>
      )}>
      <div className="off-picker-head">
        <span>
          <Icons.map /> {data?.area ? <>Jurisdiction: <b>{data.area.name}</b>{data.area.name_bn ? ` (${data.area.name_bn})` : ''}</> : 'Camera area unknown'}
          {incident.camera_location && <span className="muted"> · {incident.camera_location}</span>}
        </span>
        {canOverride && (
          <label className="off-override">
            <input type="checkbox" checked={neighbours} onChange={(e) => setNeighbours(e.target.checked)} />
            {data?.unmapped ? 'Show all officers' : 'Show neighbouring jurisdictions'} <span className="muted">(logged)</span>
          </label>
        )}
      </div>
      {data?.unmapped && (
        <div className="off-note" role="note">
          <Icons.alert />
          <span>
            <b>This camera is not inside a mapped jurisdiction</b>, so no officer covers it automatically.
            Draw its thana in Settings → Jurisdictions, or set the camera's position in Cameras → Registry.
            {canOverride ? ' You can still pick any officer below; the reason is audit-logged.' : ' A supervisor or admin can assign any officer meanwhile.'}
          </span>
        </div>
      )}
      <label className="ds-search" style={{ marginBottom: 12 }}>
        <Icons.search />
        <input className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Name, rank, badge, thana or phone" aria-label="Search officers" />
      </label>
      {loading && <SkeletonList rows={4} label="Loading officers" />}
      {!loading && error && <ErrorState compact message={error} onRetry={() => setAttempt((n) => n + 1)} />}
      {!loading && !error && list.length === 0 && (
        <EmptyState compact icon={Icons.users} title={q ? 'No officer matches' : neighbours ? 'No officers found' : 'No officer covers this camera'}
          action={!q && canOverride && !neighbours && (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => setNeighbours(true)}>
              {data?.unmapped ? 'Show all officers' : 'Show neighbouring jurisdictions'}
            </button>
          )}>
          {q ? 'Try a different name or badge number.'
            : neighbours ? 'No active field officer or supervisor accounts exist yet. Add them in Users, with role Police.'
              : canOverride ? 'Nobody is assigned to this jurisdiction yet. You can look further afield (logged).'
                : 'Nobody is assigned to this jurisdiction. Ask a supervisor to assign from a neighbouring area.'}
        </EmptyState>
      )}
      {!loading && !error && list.length > 0 && (
        <ul className="off-list" aria-label="Eligible officers">
          {list.map((o) => <OfficerCard key={o.id} o={o} selected={picked.includes(o.id)} onToggle={toggle} />)}
        </ul>
      )}
      {needReason && (
        <label className="field" style={{ marginTop: 12 }}>
          Reason for assigning outside the jurisdiction (required, audit-logged)
          <input className="input" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. All Gulshan officers busy with another incident" />
        </label>
      )}
    </Modal>
  )
}
