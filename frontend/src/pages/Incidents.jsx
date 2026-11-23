/* Incidents: filterable, sortable, paged list with live updates, and a detail drawer
   (snapshot, map, status selector, jurisdiction-checked officers, typed timeline, notes). */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { can } from '../lib/permissions'
import { Card, Icons, Modal, Stat, timeAgo } from '../components/ui'
import { AlertTypeBadge, EmptyState, ErrorState, SeverityBadge, SkeletonList } from '../components/ds'
import { StatusSelector } from '../components/StatusSelector'
import { OfficerStack } from '../components/Officers'
import { IncidentDrawer } from '../components/IncidentDrawer'
import {
  addIncidentNote, assignOfficers, createIncident, fetchAssignees, fetchIncident, fetchIncidentStats,
  fetchIncidentStatuses, fetchIncidentsPage, fetchJurisdictions, unassignOfficer, updateIncident, verifyEvidencePackage,
} from '../services/api'
import { FALLBACK_SPEC, OPEN_STATUSES, statusMeta } from '../lib/incidentStatus'
import { useToast } from '../components/Toast'
import { useI18n } from '../hooks/useI18n'
import { useWebSocket } from '../hooks/useWebSocket'

const PAGE = 25
const SEVERITIES = ['critical', 'high', 'medium', 'low']
const SOURCES = [
  { id: 'face_match', label: 'Face match' }, { id: 'vehicle_match', label: 'Vehicle match' },
  { id: 'manual', label: 'Manual' }, { id: 'alert', label: 'Other alert' },
]
const EMPTY_FILTERS = { q: '', status: [], priority: [], source: '', camera_id: '', jurisdiction_id: '', officer_id: '', date_from: '', date_to: '' }

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

function NewIncident({ cams, onClose, onCreate }) {
  const { t } = useI18n()
  const [f, setF] = useState({ title: '', description: '', priority: 'medium', camera_id: '' })
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true)
    try {
      const cam = cams.find((c) => c.camera_id === f.camera_id)
      await onCreate({ title: f.title.trim(), description: f.description.trim() || null, priority: f.priority,
        incident_type: 'MANUAL', camera_id: cam?.camera_id || null, camera_location: cam?.name || null })
    } finally { setBusy(false) }
  }
  return (
    <Modal title={t('incidents.new')} onClose={onClose}
      footer={(
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={!f.title.trim() || busy} onClick={submit}>{busy ? 'Creating…' : 'Create'}</button>
        </div>
      )}>
      <div style={{ display: 'grid', gap: 12 }}>
        <label className="field">Title<input className="input" value={f.title} maxLength={200} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
        <label className="field">Description<textarea className="input" rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
        <div className="settings-grid">
          <label className="field">Severity
            <select className="input" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>
              {SEVERITIES.map((p) => <option key={p} value={p}>{t(`severity.${p}`)}</option>)}
            </select>
          </label>
          <label className="field">Camera (sets the jurisdiction)
            <select className="input" value={f.camera_id} onChange={(e) => setF({ ...f, camera_id: e.target.value })}>
              <option value="">None</option>
              {cams.map((c) => <option key={c.camera_id} value={c.camera_id}>{c.name}</option>)}
            </select>
          </label>
        </div>
      </div>
    </Modal>
  )
}

function SortTh({ field, sort, setSort, children }) {
  const active = sort.replace('-', '') === field
  const descending = sort.startsWith('-')
  const next = active && descending ? field : `-${field}`
  return (
    <th scope="col" aria-sort={active ? (descending ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className="th-sort" onClick={() => setSort(next)}>
        {children}
        <svg viewBox="0 0 24 24" aria-hidden="true" style={{ opacity: active ? 1 : 0.35 }}>
          <path d={active && !descending ? 'M7 14l5-5 5 5' : 'M7 10l5 5 5-5'} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      </button>
    </th>
  )
}

export function Incidents({ ctx }) {
  const { push: toast } = useToast()
  const { t } = useI18n()
  const role = ctx?.me?.role
  const canEdit = can(role, 'incident.edit')
  const [spec, setSpec] = useState(FALLBACK_SPEC)
  const [stats, setStats] = useState(null)
  const [areas, setAreas] = useState([])
  const [people, setPeople] = useState([])
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [query, setQuery] = useState('')            // debounced copy of filters.q
  const [sort, setSort] = useState('-created_at')
  const [page, setPage] = useState(0)
  const [data, setData] = useState(null)
  const [loadedKey, setLoadedKey] = useState(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const [flash, setFlash] = useState(new Set())
  const [openId, setOpenId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailErr, setDetailErr] = useState('')
  const [showNew, setShowNew] = useState(false)
  // Whole registry (also cameras that are offline now): an incident may come from any of them.
  const cams = useMemo(() => {
    const byId = new Map()
    ;(ctx?.cameras || []).forEach((c) => byId.set(c.camera_id, { camera_id: c.camera_id, name: c.name || c.location || c.camera_id, location: c.location }))
    ;(ctx?.camList || []).forEach((c) => { if (!byId.has(c.camera_id)) byId.set(c.camera_id, c) })
    return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name))
  }, [ctx?.cameras, ctx?.camList])

  useEffect(() => {
    fetchIncidentStatuses().then(setSpec).catch(() => {})
    fetchJurisdictions(false).then(setAreas).catch(() => {})
    fetchAssignees().then(setPeople).catch(() => {})
  }, [])
  useEffect(() => {
    const h = setTimeout(() => setQuery(filters.q.trim()), 300)
    return () => clearTimeout(h)
  }, [filters.q])

  const params = useMemo(() => ({
    q: query, status: filters.status, priority: filters.priority, source: filters.source, camera_id: filters.camera_id,
    jurisdiction_id: filters.jurisdiction_id, officer_id: filters.officer_id,
    date_from: filters.date_from ? `${filters.date_from}T00:00:00` : '', date_to: filters.date_to ? `${filters.date_to}T23:59:59` : '',
    sort, skip: page * PAGE, limit: PAGE,
  }), [query, filters, sort, page])
  const key = JSON.stringify(params)
  const loading = loadedKey !== key && !data

  useEffect(() => {
    let off = false
    Promise.all([fetchIncidentsPage(params), fetchIncidentStats()])
      .then(([d, st]) => { if (!off) { setData(d); setStats(st); setError('') } })
      .catch((e) => { if (!off) setError(e.message || t('incidents.loadError')) })
      .finally(() => { if (!off) setLoadedKey(key) })
    return () => { off = true }
  }, [key, tick]) // eslint-disable-line react-hooks/exhaustive-deps

  const reload = useCallback(() => setTick((n) => n + 1), [])

  const loadDetail = useCallback((id) => {
    fetchIncident(id).then((d) => { setDetail(d); setDetailErr('') }).catch((e) => setDetailErr(e.message || 'Could not load incident'))
  }, [])
  const open = (id) => { setDetail(null); setDetailErr(''); setOpenId(id); loadDetail(id) }

  // Live: another operator or the pipeline changed something.
  const liveTimer = useRef(null)
  const onLive = useCallback((msg) => {
    if (msg?.event_type !== 'INCIDENT_UPDATED') return
    clearTimeout(liveTimer.current)
    liveTimer.current = setTimeout(reload, 400)
    setFlash((s) => new Set(s).add(msg.incident_id))
    setTimeout(() => setFlash((s) => { const n = new Set(s); n.delete(msg.incident_id); return n }), 2500)
    if (msg.incident_id === openId) loadDetail(openId)
  }, [reload, openId, loadDetail])
  const { connected } = useWebSocket('incidents', onLive, !!ctx?.me)

  const setF = (patch) => { setFilters((f) => ({ ...f, ...patch })); setPage(0) }
  const toggleIn = (k, v) => setF({ [k]: filters[k].includes(v) ? filters[k].filter((x) => x !== v) : [...filters[k], v] })
  const active = Object.entries(filters).some(([k, v]) => (Array.isArray(v) ? v.length : v) && k !== 'q') || !!query

  const applyUpdated = (inc) => {
    setData((d) => d && { ...d, items: d.items.map((i) => (i.id === inc.id ? { ...i, ...inc } : i)) })
    if (openId === inc.id) setDetail(inc)
    reload()
  }

  const onStatus = async (inc, status, note) => {
    try {
      const updated = await updateIncident(inc.id, { status, note })
      applyUpdated(updated)
      toast(t('incidents.statusChanged', { ticket: inc.ticket_id, status: t(`status.${status}`) }), 'ok')
    } catch (e) {
      toast(e.message || 'Could not change status', 'danger')
    }
  }
  const onAssign = async (inc, ids, opts) => {
    try {
      const updated = await assignOfficers(inc.id, ids, opts)
      applyUpdated(updated)
      toast(`${ids.length} officer(s) assigned to ${inc.ticket_id}`, 'ok')
    } catch (e) {
      toast(e.message || 'Could not assign', 'danger')
      throw e
    }
  }
  const onUnassign = async (inc, a) => {
    try {
      applyUpdated(await unassignOfficer(inc.id, a.user_id))
      toast(`${a.name} removed from ${inc.ticket_id}`, 'ok')
    } catch (e) {
      toast(e.message || 'Could not remove officer', 'danger')
    }
  }
  const onNote = async (body) => {
    try {
      await addIncidentNote(openId, body)
      loadDetail(openId)
      toast(t('incidents.noteSaved', { ticket: detail?.ticket_id }), 'ok')
      return true
    } catch (e) {
      toast(e.message || 'Could not add note', 'danger')
      return false
    }
  }
  const onCreate = async (payload) => {
    try {
      const inc = await createIncident(payload)
      setShowNew(false)
      toast(t('incidents.created', { ticket: inc.ticket_id }), 'ok')
      reload()
      open(inc.id)
    } catch (e) {
      toast(e.message || 'Could not create incident', 'danger')
    }
  }

  const by = stats?.by_status || {}
  const items = data?.items || []
  const total = data?.total || 0
  const pages = Math.max(1, Math.ceil(total / PAGE))
  const camName = (id) => cams.find((c) => c.camera_id === id)?.name

  return (
    <>
      <div className="grid grid-3 inc-stats">
        <Stat label="Open" value={stats?.open ?? '—'} delta={`${by.new || 0} new, not yet looked at`} accent={by.new ? 'danger' : 'ok'} icon={Icons.incident} />
        <Stat label="With officers" value={(by.officer_dispatched || 0) + (by.target_located || 0)} delta="Dispatched or target located" accent="warn" icon={Icons.dispatch} />
        <Stat label="Finished" value={(by.resolved || 0) + (by.closed || 0) + (by.false_alarm || 0)} delta={`${by.false_alarm || 0} false alarms · ${stats?.total ?? 0} in total`} accent="ok" icon={Icons.check} />
      </div>

      <Card
        title={t('incidents.title')}
        sub={<span className={`inc-live ${connected ? 'on' : ''}`}><span className="dot" />{connected ? 'Live' : 'Reconnecting…'} · {t('incidents.sub')}</span>}
        actions={
          <div className="ds-toolbar">
            <PackageCheck />
            {canEdit && <button type="button" className="btn btn-sm btn-primary" onClick={() => setShowNew(true)}><Icons.plus /> {t('incidents.new')}</button>}
          </div>
        }
        flush
      >
        <div className="inc-filters" role="search">
          <label className="ds-search">
            <Icons.search />
            <input className="input" type="search" value={filters.q} onChange={(e) => setF({ q: e.target.value })}
              placeholder={t('incidents.searchPh')} aria-label={t('common.search')} />
          </label>
          <select className="input" aria-label="Type" value={filters.source} onChange={(e) => setF({ source: e.target.value })}>
            <option value="">All types</option>
            {SOURCES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          <select className="input" aria-label="Camera" value={filters.camera_id} onChange={(e) => setF({ camera_id: e.target.value })}>
            <option value="">All cameras</option>
            {cams.map((c) => <option key={c.camera_id} value={c.camera_id}>{c.name}</option>)}
          </select>
          <select className="input" aria-label="Area" value={filters.jurisdiction_id} onChange={(e) => setF({ jurisdiction_id: e.target.value })}>
            <option value="">All areas</option>
            {areas.map((a) => <option key={a.id} value={a.id}>{a.level === 'thana' ? '— ' : ''}{a.name_en}</option>)}
          </select>
          <select className="input" aria-label="Assigned officer" value={filters.officer_id} onChange={(e) => setF({ officer_id: e.target.value })}>
            <option value="">Any officer</option>
            {people.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
          </select>
        </div>
        <div className="inc-filters-row2">
          <div className="inc-chipset" role="group" aria-label="Status">
            <span className="chip-label" aria-hidden="true">Status</span>
            {spec.statuses.map((s) => (
              <button key={s.id} type="button" className="inc-chip" aria-pressed={filters.status.includes(s.id)} onClick={() => toggleIn('status', s.id)}>
                {t(`status.${s.id}`)}{by[s.id] ? ` · ${by[s.id]}` : ''}
              </button>
            ))}
            <button type="button" className="inc-chip" aria-pressed={filters.status.length === OPEN_STATUSES.length && OPEN_STATUSES.every((s) => filters.status.includes(s))}
              onClick={() => setF({ status: OPEN_STATUSES })}>All open</button>
          </div>
          <div className="inc-chipset" role="group" aria-label="Severity">
            <span className="chip-label" aria-hidden="true">Severity</span>
            {SEVERITIES.map((s) => (
              <button key={s} type="button" className="inc-chip" aria-pressed={filters.priority.includes(s)} onClick={() => toggleIn('priority', s)}>{t(`severity.${s}`)}</button>
            ))}
          </div>
          <span className="chip-label" aria-hidden="true">Opened</span>
          <label>From <input className="input" type="date" value={filters.date_from} onChange={(e) => setF({ date_from: e.target.value })} /></label>
          <label>To <input className="input" type="date" value={filters.date_to} onChange={(e) => setF({ date_to: e.target.value })} /></label>
          {active && <button type="button" className="link-btn" onClick={() => { setFilters(EMPTY_FILTERS); setQuery(''); setPage(0) }}>{t('incidents.clearFilters')}</button>}
        </div>

        {loading && <SkeletonList rows={6} label="Loading incidents" />}
        {!loading && error && !data && <ErrorState title={t('incidents.loadError')} message={error} onRetry={reload} />}
        {!loading && data && items.length === 0 && (
          active
            ? <EmptyState icon={Icons.search} title={t('incidents.emptyFiltered')}
                action={<button type="button" className="btn btn-sm" onClick={() => { setFilters(EMPTY_FILTERS); setQuery(''); setPage(0) }}>{t('incidents.clearFilters')}</button>}>
                {t('incidents.emptyFilteredMsg')}
              </EmptyState>
            : <EmptyState icon={Icons.incident} title={t('incidents.empty')}
                action={canEdit && <button type="button" className="btn btn-sm btn-primary" onClick={() => setShowNew(true)}><Icons.plus /> {t('incidents.new')}</button>}>
                {t('incidents.emptyMsg')}
              </EmptyState>
        )}
        {data && items.length > 0 && (
          <>
            <div className="table-wrap table-stack" aria-busy={loadedKey !== key}>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col"><span className="sr-only">Snapshot</span></th>
                    <SortTh field="ticket_id" sort={sort} setSort={setSort}>Incident</SortTh>
                    <th scope="col">Camera</th>
                    <SortTh field="created_at" sort={sort} setSort={setSort}>Opened</SortTh>
                    <SortTh field="severity" sort={sort} setSort={setSort}>Severity</SortTh>
                    <SortTh field="status" sort={sort} setSort={setSort}>Status</SortTh>
                    <th scope="col">Officers</th>
                    <th scope="col"><span className="sr-only">Open</span></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((inc) => (
                    <tr key={inc.id} className={`inc-row ${flash.has(inc.id) ? 'live-new' : ''}`} onClick={() => open(inc.id)}>
                      <td data-label="">
                        {inc.snapshot
                          ? <img className="inc-thumb" src={`${inc.snapshot.url}${inc.snapshot.kind === 'capture' ? '?w=160' : ''}`} alt="" loading="lazy" />
                          : <span className="inc-thumb empty"><Icons.camera /></span>}
                      </td>
                      <td className="cell-wide">
                        <div className="inc-title-cell">
                          <b>{inc.title}</b>
                          <span className="meta">
                            <span className="mono">{inc.ticket_id}</span>{' · '}<AlertTypeBadge type={inc.incident_type} size="sm" />
                            {(inc.person_name || inc.plate_number) && <> · <Icons.watchlist /> {inc.person_name || <span className="mono">{inc.plate_number}</span>}</>}
                          </span>
                        </div>
                      </td>
                      <td data-label="Camera">
                        <div className="inc-title-cell">
                          <span>{camName(inc.camera_id) || inc.camera_location || '—'}</span>
                          {inc.camera_location && camName(inc.camera_id) && camName(inc.camera_id) !== inc.camera_location && <span className="meta">{inc.camera_location}</span>}
                        </div>
                      </td>
                      <td data-label="Opened" className="muted"><time dateTime={inc.created_at}>{timeAgo(inc.created_at)}</time></td>
                      <td data-label="Severity"><SeverityBadge level={inc.priority} size="sm" /></td>
                      <td data-label="Status" onClick={(e) => e.stopPropagation()}>
                        <StatusSelector spec={spec} value={inc.status} role={role} disabled={!canEdit} size="sm"
                          label={`Status of ${inc.ticket_id}`} onChange={(s, n) => onStatus(inc, s, n)} />
                      </td>
                      <td data-label="Officers"><OfficerStack assignments={inc.assignments} /></td>
                      <td className="cell-wide">
                        <button type="button" className="btn btn-sm" onClick={(e) => { e.stopPropagation(); open(inc.id) }}
                          aria-label={`Open ${inc.ticket_id}: ${statusMeta(spec, inc.status).label}`}>{t('common.open')}</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="inc-pager">
              <span>{page * PAGE + 1}–{Math.min(total, (page + 1) * PAGE)} of {total}</span>
              <div className="ds-toolbar">
                <button type="button" className="btn btn-sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button>
                <button type="button" className="btn btn-sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>Next</button>
              </div>
            </div>
          </>
        )}
      </Card>

      {openId && (
        <IncidentDrawer incident={detail} loading={!detail && !detailErr} error={detailErr} onRetry={() => loadDetail(openId)}
          spec={spec} me={ctx?.me} toast={toast} onClose={() => { setOpenId(null); setDetail(null) }}
          onStatus={onStatus} onAssign={onAssign} onUnassign={onUnassign} onNote={onNote} />
      )}
      {showNew && <NewIncident cams={cams} onClose={() => setShowNew(false)} onCreate={onCreate} />}
    </>
  )
}
