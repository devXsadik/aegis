/* Settings → Jurisdictions and Settings → Users & roles → Officers.
   Admin edits; supervisors read. The server enforces both. */
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Card, Icons, Modal, useConfirm } from './ui'
import { Badge, DsIcons, EmptyState, ErrorState, Skeleton, SkeletonList } from './ds'
import { DUTY, OfficerAvatar } from './Officers'
import {
  createJurisdiction, deleteJurisdiction, fetchJurisdictions, fetchOfficers, updateJurisdiction,
  updateOfficer, uploadOfficerPhoto,
} from '../services/api'
import { useToast } from './Toast'

const AreaMap = lazy(() => import('./AreaMap'))
const LEVELS = ['division', 'district', 'thana', 'beat']
const BLANK = { id: null, code: '', name_en: '', name_bn: '', level: 'thana', parent_id: '', geojson: null }

function useAreas() {
  const [areas, setAreas] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => fetchJurisdictions()
    .then((a) => { setAreas(a); setError('') })
    .catch((e) => setError(e.message || 'Could not load jurisdictions')), [])
  useEffect(() => { load() }, [load])
  return { areas, error, load }
}

/** Indented tree order: parents first, children under them. */
function treeOrder(areas) {
  const kids = new Map()
  areas.forEach((a) => { const k = a.parent_id || 0; kids.set(k, [...(kids.get(k) || []), a]) })
  const out = []
  const walk = (pid, depth) => (kids.get(pid) || []).sort((x, y) => x.name_en.localeCompare(y.name_en))
    .forEach((a) => { out.push({ ...a, depth }); walk(a.id, depth + 1) })
  walk(0, 0)
  const seen = new Set(out.map((a) => a.id))
  areas.filter((a) => !seen.has(a.id)).forEach((a) => out.push({ ...a, depth: 0 }))   // parent missing
  return out
}

export function JurisdictionAdmin({ isAdmin }) {
  const { push: toast } = useToast()
  const [ask, confirmDialog] = useConfirm()
  const { areas, error, load } = useAreas()
  const [form, setForm] = useState(null)
  const [drawing, setDrawing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [geoText, setGeoText] = useState('')
  const rows = useMemo(() => (areas ? treeOrder(areas) : []), [areas])

  const edit = (a) => {
    setForm(a ? { ...a, parent_id: a.parent_id || '', name_bn: a.name_bn || '' } : { ...BLANK })
    setGeoText(a?.geojson ? JSON.stringify(a.geojson) : '')
    setDrawing(false)
  }
  const onRect = useCallback((g) => { setForm((f) => f && { ...f, geojson: g }); setGeoText(JSON.stringify(g)); setDrawing(false) }, [])

  const save = async () => {
    let geojson = form.geojson
    if (geoText.trim() && geoText.trim() !== JSON.stringify(form.geojson)) {
      try { geojson = JSON.parse(geoText) } catch { toast('GeoJSON is not valid JSON', 'danger'); return }
    }
    if (!geoText.trim()) geojson = null
    setBusy(true)
    try {
      const body = { name_en: form.name_en.trim(), name_bn: form.name_bn.trim() || null, parent_id: form.parent_id ? Number(form.parent_id) : null, geojson }
      if (form.id) await updateJurisdiction(form.id, body)
      else await createJurisdiction({ ...body, code: form.code.trim(), level: form.level })
      toast(`${form.name_en} saved`, 'ok')
      setForm(null)
      load()
    } catch (e) {
      toast(e.message || 'Could not save', 'danger')
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    if (!(await ask({ title: `Delete ${form.name_en}?`, message: 'Officers lose this area and cameras in it lose their link. This is audit-logged.', confirmLabel: 'Delete', danger: true }))) return
    try {
      await deleteJurisdiction(form.id)
      toast(`${form.name_en} deleted`, 'ok')
      setForm(null)
      load()
    } catch (e) {
      toast(e.message || 'Could not delete', 'danger')
    }
  }

  return (
    <>
      <Card title="Areas" sub="Division → district → thana. Officers are offered only for cameras inside their areas."
        actions={isAdmin && <button type="button" className="btn btn-sm btn-primary" onClick={() => edit(null)}><Icons.plus /> Add area</button>} flush>
        {error && <ErrorState compact message={error} onRetry={load} />}
        {!error && !areas && <SkeletonList rows={4} />}
        {areas && areas.length === 0 && (
          <EmptyState icon={DsIcons.map} title="No jurisdictions yet"
            action={isAdmin && <button type="button" className="btn btn-sm btn-primary" onClick={() => edit(null)}>Add the first area</button>}>
            Add areas here, or run <code>python scripts/seed_jurisdictions.py</code> for the Dhaka thanas.
          </EmptyState>
        )}
        {areas && areas.length > 0 && (
          <div className="area-layout">
            <Suspense fallback={<Skeleton h={360} r={14} />}>
              <AreaMap areas={areas} selectedId={form?.id} drawing={drawing} onSelect={(id) => edit(areas.find((a) => a.id === id))} onRect={onRect} />
            </Suspense>
            <ul className="area-list" aria-label="Jurisdictions">
              {rows.map((a) => (
                <li key={a.id}>
                  <button type="button" className={`area-row ${form?.id === a.id ? 'on' : ''}`} style={{ paddingLeft: 12 + a.depth * 16 }} onClick={() => edit(a)}>
                    <span className="area-name"><b>{a.name_en}</b>{a.name_bn && <span className="muted"> · {a.name_bn}</span>}</span>
                    <span className="area-meta">
                      <Badge tone="muted" size="sm">{a.level}</Badge>
                      <Badge tone={a.officers ? 'info' : 'warn'} size="sm" icon={Icons.users}>{a.officers}</Badge>
                      {!a.geojson && <Badge tone="warn" size="sm">No boundary</Badge>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      {form && !drawing && (
        <Modal title={form.id ? `Edit ${form.name_en}` : 'Add area'} onClose={() => setForm(null)}
          footer={(
            <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', gap: 8 }}>
              <span>{isAdmin && form.id && <button type="button" className="btn btn-danger" onClick={remove}>Delete</button>}</span>
              <span style={{ display: 'flex', gap: 8 }}>
                <button type="button" className="btn" onClick={() => setForm(null)}>{isAdmin ? 'Cancel' : 'Close'}</button>
                {isAdmin && <button type="button" className="btn btn-primary" disabled={busy || !form.name_en.trim() || (!form.id && !form.code.trim())} onClick={save}>{busy ? 'Saving…' : 'Save'}</button>}
              </span>
            </div>
          )}>
          <fieldset disabled={!isAdmin} className="area-form">
            <div className="settings-grid">
              <label className="field">Code<input className="input mono" value={form.code} disabled={!!form.id} maxLength={40}
                onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} placeholder="DMP-GULSHAN" /></label>
              <label className="field">Level
                <select className="input" value={form.level} disabled={!!form.id} onChange={(e) => setForm({ ...form, level: e.target.value })}>
                  {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
                </select>
              </label>
              <label className="field">Name (English)<input className="input" value={form.name_en} maxLength={100} onChange={(e) => setForm({ ...form, name_en: e.target.value })} /></label>
              <label className="field">নাম (বাংলা)<input className="input" lang="bn" value={form.name_bn} maxLength={100} onChange={(e) => setForm({ ...form, name_bn: e.target.value })} /></label>
              <label className="field">Inside
                <select className="input" value={form.parent_id} onChange={(e) => setForm({ ...form, parent_id: e.target.value })}>
                  <option value="">— top level —</option>
                  {(areas || []).filter((a) => a.id !== form.id).map((a) => <option key={a.id} value={a.id}>{a.name_en} ({a.level})</option>)}
                </select>
              </label>
            </div>
            <label className="field" style={{ marginTop: 12 }}>
              Boundary (GeoJSON Polygon / MultiPolygon, [lng, lat])
              <textarea className="input mono" rows={4} value={geoText} onChange={(e) => setGeoText(e.target.value)}
                placeholder='{"type":"Polygon","coordinates":[[[90.41,23.775],…]]}' />
            </label>
            {isAdmin && (
              <div className="ds-toolbar" style={{ marginTop: 8 }}>
                <button type="button" className="btn btn-sm" onClick={() => setDrawing(true)}>
                  <DsIcons.map /> Draw a rectangle on the map
                </button>
                <span className="ds-setting-hint">Paste official boundaries for real use; rectangles are for quick setup.</span>
              </div>
            )}
          </fieldset>
        </Modal>
      )}
      {drawing && <div className="area-drawing-hint" role="status">Drawing: click two opposite corners on the map. <button type="button" className="link-btn" onClick={() => setDrawing(false)}>Cancel</button></div>}
      {confirmDialog}
    </>
  )
}

function OfficerEdit({ officer, areas, onClose, onSaved }) {
  const { push: toast } = useToast()
  const [f, setF] = useState({
    full_name: officer.name === officer.username ? '' : officer.name, rank: officer.rank || '', badge_no: officer.badge_no || '',
    phone: officer.phone || '', station_id: officer.station_id || '', duty_status: officer.duty_status || 'off_duty',
    jurisdiction_ids: officer.jurisdictions.map((j) => j.id),
  })
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('')
  const photo = useRef(null)
  const thanas = (areas || []).filter((a) => a.level === 'thana' || a.level === 'beat')
  const toggle = (id) => setF((x) => ({ ...x, jurisdiction_ids: x.jurisdiction_ids.includes(id) ? x.jurisdiction_ids.filter((y) => y !== id) : [...x.jurisdiction_ids, id] }))

  const save = async () => {
    setBusy(true)
    try {
      const file = photo.current?.files?.[0]
      if (file) await uploadOfficerPhoto(officer.id, file)
      await updateOfficer(officer.id, { ...f, station_id: f.station_id ? Number(f.station_id) : null })
      toast(`${f.full_name || officer.username} saved`, 'ok')
      onSaved()
      onClose()
    } catch (e) {
      toast(e.message || 'Could not save officer', 'danger')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`Officer — ${officer.username}`} onClose={onClose}
      footer={(
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      )}>
      <div className="off-edit-head">
        <OfficerAvatar id={officer.id} name={f.full_name || officer.username} hasPhoto={officer.has_photo} size={64} />
        <label className="field">Photo (JPEG / PNG / WebP, ≤ 2 MB)<input ref={photo} className="input" type="file" accept="image/jpeg,image/png,image/webp" /></label>
      </div>
      <div className="settings-grid">
        <label className="field">Full name<input className="input" value={f.full_name} maxLength={100} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></label>
        <label className="field">Rank<input className="input" list="ranks" value={f.rank} maxLength={40} onChange={(e) => setF({ ...f, rank: e.target.value })} /></label>
        <label className="field">Badge / ID<input className="input mono" value={f.badge_no} maxLength={30} onChange={(e) => setF({ ...f, badge_no: e.target.value })} /></label>
        <label className="field">Phone<input className="input mono" value={f.phone} maxLength={30} placeholder="+8801…" onChange={(e) => setF({ ...f, phone: e.target.value })} /></label>
        <label className="field">Police station (thana)
          <select className="input" value={f.station_id} onChange={(e) => setF({ ...f, station_id: e.target.value })}>
            <option value="">—</option>
            {thanas.map((a) => <option key={a.id} value={a.id}>{a.name_en}</option>)}
          </select>
        </label>
        <label className="field">Duty status
          <select className="input" value={f.duty_status} onChange={(e) => setF({ ...f, duty_status: e.target.value })}>
            {Object.entries(DUTY).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </label>
      </div>
      <datalist id="ranks">{['Constable', 'Naik', 'ASI', 'SI', 'Inspector', 'OC', 'ASP', 'Additional SP', 'SP'].map((r) => <option key={r} value={r} />)}</datalist>
      <fieldset className="off-areas">
        <legend>Jurisdictions covered ({f.jurisdiction_ids.length})</legend>
        <input className="input" type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter areas" aria-label="Filter areas" />
        <div className="off-areas-list">
          {(areas || []).filter((a) => !filter || a.name_en.toLowerCase().includes(filter.toLowerCase())).map((a) => (
            <label key={a.id} className="off-area-opt">
              <input type="checkbox" checked={f.jurisdiction_ids.includes(a.id)} onChange={() => toggle(a.id)} />
              {a.name_en} <span className="muted">· {a.level}</span>
            </label>
          ))}
        </div>
        <p className="ds-setting-hint">A district covers every thana inside it.</p>
      </fieldset>
    </Modal>
  )
}

export function OfficersAdmin({ isAdmin }) {
  const [list, setList] = useState(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [q, setQ] = useState('')
  const { areas } = useAreas()
  const load = useCallback(() => fetchOfficers()
    .then((d) => { setList(d); setError('') })
    .catch((e) => setError(e.message || 'Could not load officers')), [])
  useEffect(() => { load() }, [load])
  const shown = (list || []).filter((o) => !q || [o.name, o.username, o.badge_no, o.station, o.rank].some((v) => v && v.toLowerCase().includes(q.toLowerCase())))

  return (
    <Card title="Officers" sub="Profile, photo, rank, badge, phone, jurisdiction and duty status" flush
      actions={list && <label className="ds-search" style={{ minWidth: 200 }}><Icons.search /><input className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find officer" aria-label="Find officer" /></label>}>
      {error && <ErrorState compact message={error} onRetry={load} />}
      {!error && !list && <SkeletonList rows={4} />}
      {list && list.length === 0 && (
        <EmptyState compact icon={Icons.users} title="No officers yet">
          Create users with the <b>police</b> role on the Users page, then set their profile here.
        </EmptyState>
      )}
      {list && list.length > 0 && (
        <div className="table-wrap table-stack">
          <table className="table">
            <thead><tr><th scope="col">Officer</th><th scope="col">Badge</th><th scope="col">Station</th><th scope="col">Areas</th><th scope="col">Duty</th><th scope="col"><span className="sr-only">Edit</span></th></tr></thead>
            <tbody>
              {shown.map((o) => (
                <tr key={o.id}>
                  <td className="cell-wide">
                    <span className="off-row">
                      <OfficerAvatar id={o.id} name={o.name} hasPhoto={o.has_photo} size={34} />
                      <span className="inc-title-cell"><b>{o.rank ? `${o.rank} ` : ''}{o.name}</b><span className="meta">{o.username}{o.phone ? ` · ${o.phone}` : ''}</span></span>
                    </span>
                  </td>
                  <td data-label="Badge" className="mono">{o.badge_no || '—'}</td>
                  <td data-label="Station">{o.station || '—'}</td>
                  <td data-label="Areas">{o.jurisdictions.length ? o.jurisdictions.map((j) => j.name).join(', ') : <Badge tone="warn" size="sm">None — cannot be assigned</Badge>}</td>
                  <td data-label="Duty"><Badge tone={(DUTY[o.duty_status] || DUTY.off_duty).tone} size="sm">{(DUTY[o.duty_status] || DUTY.off_duty).label}</Badge></td>
                  <td className="cell-wide">{isAdmin && <button type="button" className="btn btn-sm" onClick={() => setEditing(o)} aria-label={`Edit ${o.name}`}>Edit</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <OfficerEdit officer={editing} areas={areas} onClose={() => setEditing(null)} onSaved={load} />}
    </Card>
  )
}
