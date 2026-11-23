/* eslint-disable react-refresh/only-export-components */
/* Watchlists with governance: approvals queue, people, vehicles, plate entry helper.
   The server enforces every rule (legal fields, second-person approval, expiry); this mirrors it. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Card, Icons, Modal, Seg, timeAgo } from './ui'
import { Badge, DsIcons, EmptyState, ErrorState, SkeletonList } from './ds'
import {
  addWatchVehicle, decideWatch, editWatchVehicle, fetchVehicleCatalog, fetchWatchApprovals,
  fetchWatchPersons, fetchWatchVehicles, normalizePlate, requestWatchPerson, uploadWatchVehiclePhoto,
} from '../services/api'
import { useToast } from './Toast'
import { parseTs } from '../lib/time'

export const WL_STATUS = {
  pending: { tone: 'warn', label: 'Pending approval', icon: Icons.clock },
  active: { tone: 'danger', label: 'Active — alerting', icon: Icons.alert },
  scheduled: { tone: 'info', label: 'Approved — starts later', icon: Icons.clock },
  expired: { tone: 'muted', label: 'Expired', icon: Icons.clock },
  rejected: { tone: 'muted', label: 'Rejected', icon: DsIcons.x },
  revoked: { tone: 'muted', label: 'Revoked', icon: DsIcons.x },
}
const RISK = { low: 'ok', medium: 'warn', high: 'orange', critical: 'danger' }
const COMMAND = ['admin', 'supervisor']
const REQUESTERS = ['operator', 'investigator', 'supervisor', 'admin']

export function WatchStatus({ entry }) {
  const st = WL_STATUS[entry.effective_status || entry.status] || { tone: 'muted', label: entry.status || 'Not listed' }
  return <Badge tone={st.tone} icon={st.icon} size="sm">{st.label}</Badge>
}

const fmtDate = (ts) => parseTs(ts)?.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' }) || '—'
const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
const daysLeft = (ts) => { const d = parseTs(ts); return d ? Math.ceil((d - Date.now()) / 86400000) : null }

/* ——— Plate entry with live canonical preview ——— */

export function PlateInput({ value, onChange, id = 'plate-input' }) {
  const [preview, setPreview] = useState(null)
  useEffect(() => {
    if (!value?.trim()) return undefined
    let off = false
    const h = setTimeout(() => normalizePlate(value).then((p) => { if (!off) setPreview(p) }).catch(() => {}), 250)
    return () => { off = true; clearTimeout(h) }
  }, [value])
  const shown = value?.trim() ? preview : null
  return (
    <div className="plate-input">
      <label className="field" htmlFor={id}>Number plate (Bangla or English)
        <input id={id} className="input plate-field" value={value} onChange={(e) => onChange(e.target.value)} maxLength={60}
          placeholder="ঢাকা মেট্রো-গ ১২-৩৪৫৬  or  Dhaka Metro Ga 12-3456" aria-describedby={`${id}-preview`} autoComplete="off" />
      </label>
      <div className="plate-helper" aria-label="Bangla letters">
        {['ঢাকা মেট্রো', 'চট্ট মেট্রো', 'ক', 'খ', 'গ', 'ঘ', 'চ', 'ছ', 'জ', 'ঝ', 'ত', 'থ', 'দ', 'ধ', 'ন', 'প', 'ব', 'ভ', 'ম', 'ল', 'হ'].map((c) => (
          <button key={c} type="button" className="plate-key" onClick={() => onChange(`${value || ''}${value && !value.endsWith(' ') ? ' ' : ''}${c}${c.includes('মেট্রো') ? '-' : ' '}`)}>{c}</button>
        ))}
      </div>
      <div id={`${id}-preview`} className="plate-preview" aria-live="polite">
        {!shown && <span className="muted">Type a plate to see how it will be matched.</span>}
        {shown && !shown.ok && <span className="plate-warn">{shown.hint}</span>}
        {shown?.ok && (
          <>
            <span className="plate-plate" lang="bn">{shown.bangla}</span>
            <span className="mono plate-canon">{shown.canonical}</span>
            {shown.complete ? <Badge tone="ok" size="sm" icon={Icons.check}>Complete</Badge> : <Badge tone="warn" size="sm">{shown.hint}</Badge>}
          </>
        )}
      </div>
    </div>
  )
}

/* ——— Legal fields ——— */

function useLegal(initial) {
  const now = new Date()
  const in90 = new Date(now.getTime() + 90 * 86400000)
  return useState({
    case_no: initial?.case_no && initial.case_no !== 'LEGACY' ? initial.case_no : '',
    offence: initial?.offence || '', risk_level: initial?.risk_level || 'medium',
    issuing_authority: initial?.issuing_authority && initial.issuing_authority !== 'Pre-governance entry' ? initial.issuing_authority : '',
    legal_basis: initial?.legal_basis?.startsWith('Legacy entry') ? '' : (initial?.legal_basis || ''),
    starts_at: toLocalInput(now), expires_at: toLocalInput(in90),
  })
}

function legalOk(f) {
  return f.case_no.trim() && f.issuing_authority.trim() && f.legal_basis.trim().length >= 10 && f.expires_at > f.starts_at
}

function LegalFields({ f, setF }) {
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  return (
    <fieldset className="legal-fields">
      <legend><DsIcons.lock /> Legal basis (required)</legend>
      <div className="settings-grid">
        <label className="field">Case / FIR / GD number<input className="input mono" value={f.case_no} maxLength={60} onChange={set('case_no')} placeholder="Gulshan FIR 77/2026" required /></label>
        <label className="field">Issuing authority<input className="input" value={f.issuing_authority} maxLength={120} onChange={set('issuing_authority')} placeholder="DMP Gulshan / CMM Court Dhaka" required /></label>
        <label className="field">Offence<input className="input" value={f.offence} maxLength={120} onChange={set('offence')} placeholder="Robbery, Section 392" /></label>
        <label className="field">Risk level
          <select className="input" value={f.risk_level} onChange={set('risk_level')}>
            {Object.keys(RISK).map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label className="field">Starts<input className="input" type="datetime-local" value={f.starts_at} onChange={set('starts_at')} /></label>
        <label className="field">Expires (max 365 days)<input className="input" type="datetime-local" value={f.expires_at} onChange={set('expires_at')} /></label>
      </div>
      <label className="field" style={{ marginTop: 10 }}>Legal basis — which law, warrant or order allows this
        <textarea className="input" rows={2} value={f.legal_basis} maxLength={2000} onChange={set('legal_basis')}
          placeholder="Arrest warrant no. … issued by … under Section … of the CrPC" required />
      </label>
      <p className="ds-setting-hint" style={{ margin: '8px 0 0' }}>
        The entry stays <b>pending</b> and raises no alert until a supervisor or admin who is not you approves it.
        It stops alerting on its own at the expiry date.
      </p>
    </fieldset>
  )
}

const legalBody = (f) => ({
  case_no: f.case_no.trim(), offence: f.offence.trim() || null, risk_level: f.risk_level,
  issuing_authority: f.issuing_authority.trim(), legal_basis: f.legal_basis.trim(),
  starts_at: new Date(f.starts_at).toISOString(), expires_at: new Date(f.expires_at).toISOString(),
})

function GovSummary({ e }) {
  const left = daysLeft(e.expires_at)
  return (
    <dl className="gov-dl">
      <div><dt>Case</dt><dd className="mono">{e.case_no || '—'}</dd></div>
      <div><dt>Authority</dt><dd>{e.issuing_authority || '—'}</dd></div>
      <div><dt>Requested</dt><dd>{e.requested_by || '—'}{e.requested_at && ` · ${timeAgo(e.requested_at)}`}</dd></div>
      <div><dt>Approved</dt><dd>{e.approved_by || (e.status === 'pending' ? 'Waiting' : '—')}</dd></div>
      <div><dt>Valid</dt><dd>{fmtDate(e.starts_at)} → {fmtDate(e.expires_at)}{left != null && left >= 0 && e.status === 'active' && <span className={left <= 7 ? 'gov-soon' : 'muted'}> · {left} d left</span>}</dd></div>
      {e.decision_note && <div><dt>Decision note</dt><dd>{e.decision_note}</dd></div>}
    </dl>
  )
}

/* ——— Decision dialog ——— */

function DecideDialog({ entry, kind, action, onClose, onDone }) {
  const { push: toast } = useToast()
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const needNote = action !== 'approve'
  const go = async () => {
    setBusy(true)
    try {
      await decideWatch(kind, kind === 'person' ? entry.person_id : entry.ref, action, note.trim())
      toast(`${kind === 'person' ? entry.name : entry.plate || entry.ref}: ${action}d`, action === 'approve' ? 'ok' : 'warn')
      onDone()
      onClose()
    } catch (e) {
      toast(e.message || `Could not ${action}`, 'danger')
    } finally {
      setBusy(false)
    }
  }
  const label = { approve: 'Approve and activate', reject: 'Reject request', revoke: 'Revoke entry' }[action]
  return (
    <Modal title={`${label}?`} onClose={onClose}
      footer={(
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className={`btn ${action === 'approve' ? 'btn-primary' : 'btn-danger'}`} disabled={busy || (needNote && note.trim().length < 3)} onClick={go}>{busy ? 'Saving…' : label}</button>
        </div>
      )}>
      <GovSummary e={entry} />
      {entry.legal_basis && <p className="gov-basis">{entry.legal_basis}</p>}
      <label className="field">{needNote ? 'Reason (required)' : 'Note (optional)'}
        <textarea className="input" rows={2} value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
      </label>
      {action === 'approve' && <p className="ds-setting-hint">From now on, cameras raise “Possible match — needs verification” alerts for this entry.</p>}
    </Modal>
  )
}

/* ——— People ——— */

function PersonRequest({ person, onClose, onDone }) {
  const { push: toast } = useToast()
  const [f, setF] = useLegal(person)
  const [aliases, setAliases] = useState((person.aliases || []).join(', '))
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true)
    try {
      await requestWatchPerson(person.person_id, { ...legalBody(f), aliases: aliases.split(',').map((a) => a.trim()).filter(Boolean) })
      toast(`${person.name}: sent for approval`, 'ok')
      onDone()
      onClose()
    } catch (e) {
      toast(e.message || 'Could not submit', 'danger')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal title={`Watchlist request — ${person.name}`} onClose={onClose}
      footer={(
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !legalOk(f)} onClick={submit}>{busy ? 'Sending…' : 'Send for approval'}</button>
        </div>
      )}>
      {person.status === 'active' && <p className="gov-warn">Changing the legal details sends this active entry back for approval: it stops alerting until approved again.</p>}
      <label className="field">Aliases (comma-separated)<input className="input" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="Kala Babu, Babu Mia" /></label>
      <LegalFields f={f} setF={setF} />
    </Modal>
  )
}

/** Fetch on mount and whenever `key` changes; `load()` refetches. */
function useList(fetcher, key) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const ref = useRef(fetcher)
  useEffect(() => { ref.current = fetcher })
  useEffect(() => {
    let off = false
    ref.current().then((d) => { if (!off) { setData(d); setError('') } }).catch((e) => { if (!off) setError(e.message || 'Could not load') })
    return () => { off = true }
  }, [key, tick])
  const load = useCallback(() => setTick((n) => n + 1), [])
  return { data, error, load }
}

export function PersonWatchlist({ role }) {
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [qq, setQq] = useState('')
  useEffect(() => { const h = setTimeout(() => setQq(q.trim()), 300); return () => clearTimeout(h) }, [q])
  const { data, error, load } = useList(() => fetchWatchPersons({ status, q: qq }), `${status}|${qq}`)
  const [req, setReq] = useState(null)
  const [decide, setDecide] = useState(null)
  const canRequest = REQUESTERS.includes(role)
  const canDecide = COMMAND.includes(role)
  const notListed = useMemo(() => (data || []).filter((p) => !p.status), [data])

  return (
    <Card title="People" sub="Criminal profiles on the watchlist. Photos and face enrolment are on the People page." flush
      actions={<div className="ds-toolbar">
        <label className="ds-search" style={{ minWidth: 200 }}><Icons.search /><input className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, alias, case no." aria-label="Search people" /></label>
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All</option>{Object.entries(WL_STATUS).filter(([k]) => k !== 'scheduled').map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      </div>}>
      {error && <ErrorState compact message={error} onRetry={load} />}
      {!error && !data && <SkeletonList rows={4} />}
      {data && data.length === 0 && <EmptyState compact icon={Icons.watchlist} title="No people match">Enrol a person in the criminal category on the People page, then request a watchlist entry here.</EmptyState>}
      {data && data.length > 0 && (
        <ul className="wl-list">
          {data.map((p) => (
            <li key={p.person_id} className="wl-item">
              <div className="wl-main">
                <div className="wl-title">
                  <b>{p.name}</b>
                  <span className="mono muted">{p.person_id}</span>
                  {p.status ? <WatchStatus entry={p} /> : <Badge tone="muted" size="sm">Not requested</Badge>}
                  {p.risk_level && <Badge tone={RISK[p.risk_level]} size="sm">Risk: {p.risk_level}</Badge>}
                  {p.needs_review && <Badge tone="warn" size="sm" icon={Icons.alert}>Legacy — needs review</Badge>}
                </div>
                {p.aliases?.length > 0 && <div className="meta">Also known as {p.aliases.join(', ')}</div>}
                {p.offence && <div className="meta">{p.offence}</div>}
                {p.status && <GovSummary e={p} />}
              </div>
              <div className="wl-actions">
                {canRequest && <button type="button" className="btn btn-sm" onClick={() => setReq(p)}>{p.status ? 'Update / renew' : 'Request entry'}</button>}
                {canDecide && p.status === 'pending' && <>
                  <button type="button" className="btn btn-sm btn-primary" onClick={() => setDecide({ entry: p, action: 'approve' })}>Approve</button>
                  <button type="button" className="btn btn-sm" onClick={() => setDecide({ entry: p, action: 'reject' })}>Reject</button>
                </>}
                {canDecide && p.status === 'active' && <button type="button" className="btn btn-sm" onClick={() => setDecide({ entry: p, action: 'revoke' })}>Revoke</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {canRequest && notListed.length > 0 && (
        <p className="ds-setting-hint" style={{ padding: '0 16px 14px' }}>
          {notListed.length} criminal profile(s) have no watchlist entry yet and raise no alerts.
        </p>
      )}
      {req && <PersonRequest person={req} onClose={() => setReq(null)} onDone={load} />}
      {decide && <DecideDialog entry={decide.entry} kind="person" action={decide.action} onClose={() => setDecide(null)} onDone={load} />}
    </Card>
  )
}

/* ——— Vehicles ——— */

function useCatalog() {
  const [cat, setCat] = useState({ type: [], color: [], model: [] })
  useEffect(() => {
    fetchVehicleCatalog().then((rows) => {
      const by = { type: [], color: [], make: [], model: [] }
      rows.forEach((r) => by[r.kind]?.push(r))
      setCat(by)
    }).catch(() => {})
  }, [])
  return cat
}

function VehicleForm({ entry, onClose, onDone }) {
  const { push: toast } = useToast()
  const cat = useCatalog()
  const [v, setV] = useState({
    plate: entry?.plate || '', vehicle_type: entry?.vehicle_type || '', color_primary: entry?.color_primary || '',
    color_secondary: entry?.color_secondary || '', make_model: entry?.make_model || '', marks: entry?.marks || '', notes: entry?.notes || '',
  })
  const [f, setF] = useLegal(entry)
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const [modelQ, setModelQ] = useState('')
  const identOk = v.plate.trim() || (v.vehicle_type && v.color_primary)
  const set = (k) => (e) => setV({ ...v, [k]: e.target.value })
  const models = cat.model.filter((m) => !modelQ || m.name_en.toLowerCase().includes(modelQ.toLowerCase()))

  const submit = async () => {
    setBusy(true)
    try {
      const body = { ...Object.fromEntries(Object.entries(v).map(([k, x]) => [k, x.trim?.() ? x.trim() : null])), ...legalBody(f) }
      const saved = entry ? await editWatchVehicle(entry.ref, body) : await addWatchVehicle(body)
      for (const file of files) await uploadWatchVehiclePhoto(saved.ref, file)
      toast(`${saved.plate || saved.ref}: sent for approval`, 'ok')
      onDone()
      onClose()
    } catch (e) {
      toast(e.message || 'Could not save vehicle', 'danger')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal className="wl-vehicle-modal" title={entry ? `Vehicle ${entry.ref}` : 'Add vehicle to the watchlist'} onClose={onClose}
      footer={(
        <div className="off-picker-foot">
          <span className="muted">{identOk ? '' : 'Give a plate, or at least type and colour'}</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button type="button" className="btn btn-primary" disabled={busy || !identOk || !legalOk(f)} onClick={submit}>{busy ? 'Saving…' : 'Send for approval'}</button>
          </div>
        </div>
      )}>
      <PlateInput value={v.plate} onChange={(x) => setV({ ...v, plate: x })} />
      <div className="settings-grid" style={{ marginTop: 12 }}>
        <label className="field">Type
          <select className="input" value={v.vehicle_type} onChange={set('vehicle_type')}>
            <option value="">Unknown</option>{cat.type.map((c) => <option key={c.code} value={c.code}>{c.name_en}{c.name_bn ? ` · ${c.name_bn}` : ''}</option>)}
          </select>
        </label>
        <label className="field">Make / model
          <input className="input" type="search" value={modelQ} onChange={(e) => setModelQ(e.target.value)} placeholder="Search: Axio, Noah, Bajaj…" aria-label="Search make and model" />
          <select className="input" value={v.make_model} onChange={set('make_model')} size={1} aria-label="Make and model">
            <option value="">Unknown</option>{models.map((c) => <option key={c.code} value={c.code}>{c.name_en}</option>)}
          </select>
        </label>
        <div className="field">Primary colour
          <div className="swatches" role="radiogroup" aria-label="Primary colour">
            {cat.color.map((c) => <button key={c.code} type="button" role="radio" aria-checked={v.color_primary === c.code} title={c.name_en}
              className={`swatch sw-${c.code}`} onClick={() => setV({ ...v, color_primary: v.color_primary === c.code ? '' : c.code })}><span className="sr-only">{c.name_en}</span></button>)}
          </div>
        </div>
        <div className="field">Second colour (optional)
          <div className="swatches" role="radiogroup" aria-label="Second colour">
            {cat.color.map((c) => <button key={c.code} type="button" role="radio" aria-checked={v.color_secondary === c.code} title={c.name_en}
              className={`swatch sw-${c.code}`} onClick={() => setV({ ...v, color_secondary: v.color_secondary === c.code ? '' : c.code })}><span className="sr-only">{c.name_en}</span></button>)}
          </div>
        </div>
        <label className="field">Distinguishing marks<input className="input" value={v.marks} onChange={set('marks')} placeholder="Roof rack, dent on left door, company logo" /></label>
        <label className="field">Photos (used to recognise the vehicle)<input className="input" type="file" multiple accept="image/jpeg,image/png,image/webp" onChange={(e) => setFiles([...e.target.files])} /></label>
      </div>
      <label className="field" style={{ marginTop: 10 }}>Notes<textarea className="input" rows={2} value={v.notes} onChange={set('notes')} /></label>
      <LegalFields f={f} setF={setF} />
    </Modal>
  )
}

const catName = (list, code) => list.find((c) => c.code === code)?.name_en || code

export function VehicleWatchlist({ role }) {
  const cat = useCatalog()
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [qq, setQq] = useState('')
  useEffect(() => { const h = setTimeout(() => setQq(q.trim()), 300); return () => clearTimeout(h) }, [q])
  const { data, error, load } = useList(() => fetchWatchVehicles({ status, q: qq }), `${status}|${qq}`)
  const [form, setForm] = useState(null)
  const [decide, setDecide] = useState(null)
  const canRequest = REQUESTERS.includes(role)
  const canDecide = COMMAND.includes(role)

  return (
    <Card title="Vehicles" sub="Plate and / or type, colour and model. Plate-less entries alert only inside a lookout area." flush
      actions={<div className="ds-toolbar">
        <label className="ds-search" style={{ minWidth: 200 }}><Icons.search /><input className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Plate (Bangla or English), case" aria-label="Search vehicles" /></label>
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All</option>{Object.entries(WL_STATUS).filter(([k]) => k !== 'scheduled').map(([k, x]) => <option key={k} value={k}>{x.label}</option>)}
        </select>
        {canRequest && <button type="button" className="btn btn-sm btn-primary" onClick={() => setForm({})}><Icons.plus /> Add vehicle</button>}
      </div>}>
      {error && <ErrorState compact message={error} onRetry={load} />}
      {!error && !data && <SkeletonList rows={4} />}
      {data && data.length === 0 && (
        <EmptyState compact icon={Icons.vehicle} title="No vehicles on the watchlist"
          action={canRequest && <button type="button" className="btn btn-sm btn-primary" onClick={() => setForm({})}>Add a vehicle</button>}>
          Entries need a case number and a second person's approval before they alert.
        </EmptyState>
      )}
      {data && data.length > 0 && (
        <ul className="wl-list">
          {data.map((v) => (
            <li key={v.ref} className="wl-item">
              {v.photos[0] ? <img className="wl-photo" src={v.photos[0].url} alt="" loading="lazy" /> : <span className="wl-photo empty"><Icons.vehicle /></span>}
              <div className="wl-main">
                <div className="wl-title">
                  {v.plate ? <span className="plate-chip" lang="bn">{v.plate_bangla || v.plate}</span> : <Badge tone="muted" size="sm">No plate</Badge>}
                  <WatchStatus entry={v} />
                  <Badge tone={RISK[v.risk_level]} size="sm">Risk: {v.risk_level}</Badge>
                  {v.needs_review && <Badge tone="warn" size="sm" icon={Icons.alert}>Legacy — needs review</Badge>}
                </div>
                <div className="meta">
                  {[v.color_primary && catName(cat.color, v.color_primary), v.color_secondary && `/ ${catName(cat.color, v.color_secondary)}`,
                    v.make_model && catName(cat.model, v.make_model), v.vehicle_type && catName(cat.type, v.vehicle_type)].filter(Boolean).join(' ') || 'Attributes unknown'}
                  {v.linked_person && <> · linked to <b>{v.linked_person.name}</b></>}
                  {v.plate_canonical && <span className="mono"> · {v.plate_canonical}</span>}
                </div>
                {v.marks && <div className="meta">Marks: {v.marks}</div>}
                <GovSummary e={v} />
              </div>
              <div className="wl-actions">
                {canRequest && !['rejected', 'revoked'].includes(v.status) && <button type="button" className="btn btn-sm" onClick={() => setForm(v)}>Edit / renew</button>}
                {canDecide && v.status === 'pending' && <>
                  <button type="button" className="btn btn-sm btn-primary" onClick={() => setDecide({ entry: v, action: 'approve' })}>Approve</button>
                  <button type="button" className="btn btn-sm" onClick={() => setDecide({ entry: v, action: 'reject' })}>Reject</button>
                </>}
                {canDecide && v.status === 'active' && <button type="button" className="btn btn-sm" onClick={() => setDecide({ entry: v, action: 'revoke' })}>Revoke</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {form && <VehicleForm entry={form.ref ? form : null} onClose={() => setForm(null)} onDone={load} />}
      {decide && <DecideDialog entry={decide.entry} kind="vehicle" action={decide.action} onClose={() => setDecide(null)} onDone={load} />}
    </Card>
  )
}

/* ——— Approvals ——— */

export function ApprovalsQueue() {
  const { data, error, load } = useList(fetchWatchApprovals, 'approvals')
  const [decide, setDecide] = useState(null)
  const items = data ? [...data.persons.map((p) => ({ kind: 'person', e: p })), ...data.vehicles.map((v) => ({ kind: 'vehicle', e: v }))] : []
  return (
    <Card title="Waiting for approval" sub="Second-person rule: you cannot approve what you requested" flush>
      {error && <ErrorState compact message={error} onRetry={load} />}
      {!error && !data && <SkeletonList rows={3} />}
      {data?.legacy_needing_review > 0 && <p className="gov-warn" style={{ margin: '12px 16px 0' }}>{data.legacy_needing_review} legacy entr{data.legacy_needing_review === 1 ? 'y' : 'ies'} from before governance alert for 30 days only. Add the legal details to keep them.</p>}
      {data && items.length === 0 && <EmptyState compact icon={Icons.check} title="Nothing waiting">New requests appear here.</EmptyState>}
      {items.length > 0 && (
        <ul className="wl-list">
          {items.map(({ kind, e }) => (
            <li key={`${kind}-${e.person_id || e.ref}`} className="wl-item">
              <span className="wl-photo empty">{kind === 'person' ? <Icons.watchlist /> : <Icons.vehicle />}</span>
              <div className="wl-main">
                <div className="wl-title"><b>{kind === 'person' ? e.name : (e.plate_bangla || e.plate || e.ref)}</b><Badge tone="muted" size="sm">{kind}</Badge>{e.risk_level && <Badge tone={RISK[e.risk_level]} size="sm">Risk: {e.risk_level}</Badge>}</div>
                <GovSummary e={e} />
                <p className="gov-basis">{e.legal_basis}</p>
              </div>
              <div className="wl-actions">
                <button type="button" className="btn btn-sm btn-primary" disabled={!e.can_approve} title={e.can_approve ? '' : 'You requested this: another supervisor must approve'}
                  onClick={() => setDecide({ kind, entry: e, action: 'approve' })}>Approve</button>
                <button type="button" className="btn btn-sm" onClick={() => setDecide({ kind, entry: e, action: 'reject' })}>Reject</button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {decide && <DecideDialog entry={decide.entry} kind={decide.kind} action={decide.action} onClose={() => setDecide(null)} onDone={load} />}
    </Card>
  )
}

export function WatchlistAdmin({ role }) {
  const command = COMMAND.includes(role)
  const [tab, setTab] = useState(command ? 'approvals' : 'people')
  return (
    <>
      <Seg value={tab} onChange={setTab} options={[
        ...(command ? [{ value: 'approvals', label: 'Approvals' }] : []),
        { value: 'people', label: 'People' }, { value: 'vehicles', label: 'Vehicles' },
      ]} />
      {tab === 'approvals' && <ApprovalsQueue />}
      {tab === 'people' && <PersonWatchlist role={role} />}
      {tab === 'vehicles' && <VehicleWatchlist role={role} />}
    </>
  )
}
