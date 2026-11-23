import { useEffect, useRef, useState } from 'react'
import { can } from '../lib/permissions'
import { Card, Icons, Stat, timeAgo, Modal } from '../components/ui'
import { AlertTypeBadge, EmptyState, ErrorState, SeverityBadge, SkeletonList, StatusBadge } from '../components/ds'
import { useI18n } from '../hooks/useI18n'
import {
  fetchIncidents, fetchIncidentStats, updateIncident, addIncidentNote, createIncident, fetchAssignees,
  downloadEvidencePackage, verifyEvidencePackage,
} from '../services/api'
import { useToast } from '../components/Toast'
const STATUSES = ['open', 'investigating', 'resolved', 'closed']
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : '')
const matches = (inc, q) => !q || [inc.ticket_id, inc.title, inc.camera_location, inc.person_name, inc.plate_number, inc.assigned_name]
  .some((v) => v && String(v).toLowerCase().includes(q))

/** Upload a package to check it came from this system and nothing in it changed. */
function PackageCheck() {
  const ref = useRef(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const check = async (file) => {
    if (!file) return
    setBusy(true); setResult(null)
    try { setResult({ name: file.name, ...(await verifyEvidencePackage(file)) }) } catch (e) { setResult({ name: file.name, ok: false, error: e.message }) } finally { setBusy(false); ref.current.value = '' }
  }
  return (
    <>
      <input ref={ref} type="file" accept=".zip" hidden onChange={(e) => check(e.target.files[0])} />
      <button type="button" className="btn btn-sm" disabled={busy} onClick={() => ref.current.click()}>
        <Icons.shield /> {busy ? 'Checking…' : 'Check a package'}
      </button>
      {result && (
        <Modal title="Evidence package check" onClose={() => setResult(null)}>
          <p className={result.ok ? 'pkg-ok' : 'pkg-bad'}>
            {result.ok
              ? `${result.name}: intact. All ${result.files_checked} files match the manifest, and the signature is this system's.`
              : `${result.name}: NOT intact.`}
          </p>
          {!result.ok && (
            <ul className="pkg-problems">
              {result.error && <li>{result.error}</li>}
              {result.signature_valid === false && <li>The signature does not match: not exported by this system, or the manifest was edited.</li>}
              {result.changed_or_missing?.map((n) => <li key={n}>Changed or missing: <code>{n}</code></li>)}
              {result.unlisted_files?.map((n) => <li key={n}>Added after export: <code>{n}</code></li>)}
            </ul>
          )}
        </Modal>
      )}
    </>
  )
}

export function Incidents({ ctx }) {
  const { push: toast } = useToast()
  const { t } = useI18n()
  const canEdit = can(ctx?.me?.role, 'incident.edit')
  const [assignees, setAssignees] = useState([])
  const [showNew, setShowNew] = useState(false)
  const [newForm, setNewForm] = useState({ title: '', description: '', priority: 'medium' })
  useEffect(() => { fetchAssignees().then(setAssignees).catch(() => {}) }, [])
  const [incidents, setIncidents] = useState([])
  const [stats, setStats] = useState(null)
  const [selected, setSelected] = useState(null)
  const [note, setNote] = useState('')
  const [filter, setFilter] = useState('all')
  const [loadedFilter, setLoadedFilter] = useState(null)   // which filter the list on screen belongs to
  const loading = loadedFilter !== filter
  const [loadError, setLoadError] = useState('')
  const [query, setQuery] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [list, st] = await Promise.all([
          fetchIncidents(filter === 'all' ? {} : { status: filter }),
          fetchIncidentStats(),
        ])
        if (!cancelled) {
          setIncidents(list)
          setStats(st)
          setLoadError('')
        }
      } catch (e) {
        if (!cancelled) { setIncidents([]); setLoadError(e.message || 'Could not load incidents') }
      } finally {
        if (!cancelled) setLoadedFilter(filter)
      }
    })()
    return () => { cancelled = true }
  }, [filter, attempt])
  const retry = () => { setLoadedFilter(null); setAttempt((n) => n + 1) }

  const reload = async () => {
    const [list, st] = await Promise.all([
      fetchIncidents(filter === 'all' ? {} : { status: filter }),
      fetchIncidentStats(),
    ])
    setIncidents(list)
    setStats(st)
  }

  const patch = async (id, body) => {
    try {
      const updated = await updateIncident(id, body)
      setIncidents((prev) => prev.map((i) => (i.id === id ? updated : i)))
      if (selected?.id === id) setSelected(updated)
      const ticket = updated.ticket_id
      if (body.status) toast(t('incidents.statusChanged', { ticket, status: t(`status.${body.status}`) }), 'ok')
      else if ('assigned_to' in body) {
        toast(updated.assigned_name ? t('incidents.assigned', { ticket, name: updated.assigned_name }) : t('incidents.unassigned', { ticket }), 'ok')
      }
      reload().catch(() => {})
    } catch (e) {
      toast(e.message || 'Update failed', 'danger')
    }
  }

  const submitNote = async () => {
    if (!selected || !note.trim()) return
    try {
      await addIncidentNote(selected.id, note.trim())
      setNote('')
      const refreshed = await fetchIncidents(filter === 'all' ? {} : { status: filter })
      const found = refreshed.find((i) => i.id === selected.id)
      setIncidents(refreshed)
      if (found) setSelected(found)
      toast(t('incidents.noteSaved', { ticket: selected.ticket_id }), 'ok')
    } catch (e) {
      toast(e.message || 'Could not add note', 'danger')
    }
  }

  const createManual = async () => {
    try {
      const inc = await createIncident({
        title: newForm.title.trim(),
        description: newForm.description.trim() || null,
        priority: newForm.priority,
        incident_type: 'MANUAL',
      })
      setIncidents((prev) => [inc, ...prev])
      setSelected(inc)
      setShowNew(false)
      setNewForm({ title: '', description: '', priority: 'medium' })
      toast(t('incidents.created', { ticket: inc.ticket_id }), 'ok')
    } catch (e) {
      toast(e.message || 'Could not create incident', 'danger')
    }
  }

  const by = stats?.by_status || {}
  const q = query.trim().toLowerCase()
  const shown = incidents.filter((i) => matches(i, q))
  const filtered = filter !== 'all' || !!q

  return (
    <>
      <div className="grid grid-3 inc-stats">
        <Stat label={t('status.open')} value={by.open || 0} delta="Waiting for someone to pick up" accent={by.open ? 'danger' : 'ok'} icon={Icons.incident} />
        <Stat label={t('status.investigating')} value={by.investigating || 0} delta="Being worked on" accent="warn" icon={Icons.search} />
        <Stat label="Resolved or closed" value={(by.resolved || 0) + (by.closed || 0)} delta={`${stats?.total ?? 0} incidents in total`} accent="ok" icon={Icons.check} />
      </div>

      <Card
        title={t('incidents.title')}
        sub={t('incidents.sub')}
        actions={
          <div className="ds-toolbar">
            <PackageCheck />
            {canEdit && <button type="button" className="btn btn-sm btn-primary" onClick={() => setShowNew(true)}><Icons.plus /> {t('incidents.new')}</button>}
          </div>
        }
        flush
      >
        <div className="ds-toolbar" style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <label className="ds-search">
            <Icons.search />
            <input className="input" type="search" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder={t('incidents.searchPh')} aria-label={t('common.search')} />
          </label>
          <select className="input" aria-label="Filter by status" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">All statuses</option>
            {STATUSES.map((st) => <option key={st} value={st}>{t(`status.${st}`)}</option>)}
          </select>
        </div>
        {loading && <SkeletonList rows={5} label="Loading incidents" />}
        {!loading && loadError && <ErrorState title={t('incidents.loadError')} message={loadError} onRetry={retry} />}
        {!loading && !loadError && shown.length === 0 && (
          filtered
            ? <EmptyState icon={Icons.search} title={t('incidents.emptyFiltered')}
                action={<button type="button" className="btn btn-sm" onClick={() => { setQuery(''); setFilter('all') }}>{t('incidents.clearFilters')}</button>}>
                {t('incidents.emptyFilteredMsg')}
              </EmptyState>
            : <EmptyState icon={Icons.incident} title={t('incidents.empty')}
                action={canEdit && <button type="button" className="btn btn-sm btn-primary" onClick={() => setShowNew(true)}><Icons.plus /> {t('incidents.new')}</button>}>
                {t('incidents.emptyMsg')}
              </EmptyState>
        )}
        {!loading && !loadError && shown.length > 0 && (
          <div className="table-wrap table-stack">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Incident</th><th scope="col">Type</th><th scope="col">Severity</th><th scope="col">Camera</th>
                <th scope="col">Officer</th><th scope="col">Status</th><th scope="col">Opened</th><th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((inc) => (
                <tr key={inc.id}>
                  <td className="cell-wide">
                    <div className="inc-title-cell">
                      <b>{inc.title}</b>
                      <span className="meta mono">{inc.ticket_id}{inc.person_name ? ` · ${inc.person_name}` : ''}{inc.plate_number ? ` · ${inc.plate_number}` : ''}</span>
                    </div>
                  </td>
                  <td data-label="Type"><AlertTypeBadge type={inc.incident_type} size="sm" /></td>
                  <td data-label="Severity"><SeverityBadge level={inc.priority} size="sm" /></td>
                  <td data-label="Camera">{inc.camera_location || '—'}</td>
                  <td data-label="Officer">
                    <select
                      className="input" style={{ padding: '4px 8px', fontSize: '0.78rem' }}
                      aria-label={`Assignee for ${inc.ticket_id}`}
                      disabled={!canEdit}
                      value={inc.assigned_to || 0}
                      onChange={(e) => patch(inc.id, { assigned_to: Number(e.target.value) })}
                    >
                      <option value={0}>Unassigned</option>
                      {assignees.map((u) => <option key={u.id} value={u.id}>{u.username} ({u.role})</option>)}
                    </select>
                  </td>
                  <td data-label="Status">
                    {canEdit ? (
                      <select
                        className="input" style={{ padding: '4px 8px', fontSize: '0.78rem' }}
                        aria-label={`Status for ${inc.ticket_id}`}
                        value={inc.status}
                        onChange={(e) => patch(inc.id, { status: e.target.value })}
                      >
                        {STATUSES.map((st) => <option key={st} value={st}>{t(`status.${st}`)}</option>)}
                      </select>
                    ) : <StatusBadge status={inc.status} size="sm" />}
                  </td>
                  <td data-label="Opened" className="muted"><time dateTime={inc.created_at}>{timeAgo(inc.created_at)}</time></td>
                  <td className="cell-wide"><button type="button" className="btn btn-sm" onClick={() => setSelected(inc)} aria-label={`Open ${inc.ticket_id}`}>{t('common.open')}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </Card>

      {selected && (
        <Modal
          title={`${selected.ticket_id} — ${selected.title}`}
          onClose={() => setSelected(null)}
          footer={
            <>
              <button className="btn" onClick={() => window.print()}><Icons.report /> Print</button>
              <button className="btn" onClick={() => { downloadEvidencePackage(selected.id); toast('Building the evidence package: the download starts in a moment', 'ok') }}>
                <Icons.download /> Evidence package
              </button>
              {canEdit && !['resolved', 'closed'].includes(selected.status) && (
                <button className="btn btn-primary" onClick={() => patch(selected.id, { status: 'resolved' })}>
                  <Icons.check /> Mark as resolved
                </button>
              )}
            </>
          }
        >
          <dl className="inc-detail-grid">
            <div><dt>Status</dt><dd><StatusBadge status={selected.status} /></dd></div>
            <div><dt>Severity</dt><dd><SeverityBadge level={selected.priority} /></dd></div>
            <div><dt>Type</dt><dd><AlertTypeBadge type={selected.incident_type} /></dd></div>
            <div><dt>Officer</dt><dd>{selected.assigned_name || 'Unassigned'}</dd></div>
            <div><dt>Camera</dt><dd>{selected.camera_location || '—'}</dd></div>
            <div><dt>Opened</dt><dd>{timeAgo(selected.created_at)}</dd></div>
            {selected.person_name && <div><dt>Subject</dt><dd>{selected.person_name}</dd></div>}
            {selected.lat != null && (
              <div><dt>GPS</dt><dd className="mono">{Number(selected.lat).toFixed(5)}, {Number(selected.lng).toFixed(5)}</dd></div>
            )}
          </dl>

          <h4 className="inc-section-title">Timeline</h4>
          <div className="timeline" style={{ marginBottom: 18 }}>
            {(selected.events || []).length === 0 && <EmptyState compact icon={Icons.clock}>No events yet</EmptyState>}
            {(selected.events || []).map((ev) => (
              <div key={ev.id} className="timeline-item">
                <div className="t-time">{timeAgo(ev.created_at)} · {ev.actor}</div>
                <b>{ev.event_type}</b> — {ev.message}
              </div>
            ))}
          </div>

          <h4 className="inc-section-title">Notes</h4>
          {(selected.notes || []).map((n) => (
            <div key={n.id} className="row">
              <div>
                <b>{n.author_name}</b>
                <div className="meta">{n.body}</div>
              </div>
              <span className="muted" style={{ fontSize: '0.72rem' }}>{timeAgo(n.created_at)}</span>
            </div>
          ))}
          {(selected.notes || []).length === 0 && <EmptyState compact icon={Icons.report}>No notes yet</EmptyState>}
          {canEdit && (
            <>
              <label className="field" style={{ marginTop: 12 }}>
                Add note
                <textarea className="input" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you find?" />
              </label>
              <button className="btn btn-sm btn-primary" style={{ marginTop: 8 }} onClick={submitNote} disabled={!note.trim()}>
                Save note
              </button>
            </>
          )}
        </Modal>
      )}
      {showNew && (
        <Modal
          title={t('incidents.new')}
          onClose={() => setShowNew(false)}
          footer={(
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="btn" onClick={() => setShowNew(false)}>Cancel</button>
              <button className="btn btn-primary" disabled={!newForm.title.trim()} onClick={createManual}>Create</button>
            </div>
          )}
        >
          <div style={{ display: 'grid', gap: 10 }}>
            <label className="field">Title
              <input className="input" value={newForm.title} maxLength={200} onChange={(e) => setNewForm({ ...newForm, title: e.target.value })} />
            </label>
            <label className="field">Description
              <textarea className="input" rows={3} value={newForm.description} onChange={(e) => setNewForm({ ...newForm, description: e.target.value })} />
            </label>
            <label className="field">Priority
              <select className="input" value={newForm.priority} onChange={(e) => setNewForm({ ...newForm, priority: e.target.value })}>
                {['low', 'medium', 'high', 'critical'].map((p) => <option key={p} value={p}>{cap(p)}</option>)}
              </select>
            </label>
          </div>
        </Modal>
      )}
    </>
  )
}
