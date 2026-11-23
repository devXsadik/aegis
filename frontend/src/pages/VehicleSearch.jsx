/* Vehicle Search (spec 7.6): recent detections by partial plate, type, colour, make/model, area,
   cameras and time — or by photo (re-ID). Every search needs a reason and is audit-logged. From a
   result: view on map, open an incident, or start a live lookout for the area. */
import { Fragment, useEffect, useState } from 'react'
import { Card, Icons, Modal, Seg, timeAgo } from '../components/ui'
import { Badge, EmptyState, ErrorState, SkeletonList } from '../components/ds'
import {
  cancelLookout, createIncident, fetchJurisdictions, fetchLookouts, fetchVehicleCatalog, searchVehicles,
  searchVehiclesByPhoto, startLookout,
} from '../services/api'
import { useToast } from '../components/Toast'
import { fetchRegistryStatus, registryLookup } from '../services/api'
import { parseTs } from '../lib/time'

const pct = (v) => (v == null ? '' : `${Math.round(v * 100)}%`)

function Chips({ label, options, value, onChange }) {
  return (
    <div className="field">{label}
      <div className="inc-chipset" role="group" aria-label={label}>
        {options.map((o) => (
          <button key={o.code} type="button" className="inc-chip" aria-pressed={value.includes(o.code)}
            onClick={() => onChange(value.includes(o.code) ? value.filter((x) => x !== o.code) : [...value, o.code])}>
            {o.name_en}
          </button>
        ))}
      </div>
    </div>
  )
}

function LookoutDialog({ seed, areas, onClose, onDone }) {
  const { push: toast } = useToast()
  const [f, setF] = useState({ reason: seed.reason || '', hours: 4, jurisdiction_id: seed.jurisdiction_id || '', plate: seed.plate || '',
    vehicle_type: seed.vehicle_type || '', color_primary: seed.color || '', make_model: seed.make_model || '' })
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true)
    try {
      const b = await startLookout({
        kind: 'vehicle', reason: f.reason.trim(), hours: Number(f.hours), plate: f.plate || null,
        vehicle_type: f.vehicle_type || null, color_primary: f.color_primary || null, make_model: f.make_model || null,
        jurisdiction_id: f.jurisdiction_id ? Number(f.jurisdiction_id) : null, camera_ids: f.jurisdiction_id ? [] : seed.camera_ids || [],
      })
      toast(`Lookout ${b.ref} active on ${b.cameras.length} camera(s) for ${f.hours} h`, 'ok')
      onDone()
      onClose()
    } catch (e) {
      toast(e.message || 'Could not start lookout', 'danger')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal title="Start a live lookout" onClose={onClose}
      footer={<div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-primary" disabled={busy || f.reason.trim().length < 5} onClick={go}>{busy ? 'Starting…' : 'Start lookout'}</button>
      </div>}>
      <p className="ds-setting-hint" style={{ marginTop: 0 }}>Cameras in the area analyse more frames, and vehicles that match the description raise “Candidate vehicle” alerts even without a plate — only there, only until it ends.</p>
      <div className="settings-grid">
        <label className="field">Plate (optional)<input className="input" value={f.plate} onChange={(e) => setF({ ...f, plate: e.target.value })} /></label>
        <label className="field">Type<input className="input" value={f.vehicle_type} onChange={(e) => setF({ ...f, vehicle_type: e.target.value })} /></label>
        <label className="field">Colour<input className="input" value={f.color_primary} onChange={(e) => setF({ ...f, color_primary: e.target.value })} /></label>
        <label className="field">Make / model<input className="input" value={f.make_model} onChange={(e) => setF({ ...f, make_model: e.target.value })} /></label>
        <label className="field">Area
          <select className="input" value={f.jurisdiction_id} onChange={(e) => setF({ ...f, jurisdiction_id: e.target.value })}>
            <option value="">{seed.camera_ids?.length ? `Only camera ${seed.camera_ids.join(', ')}` : 'Choose an area'}</option>
            {areas.map((a) => <option key={a.id} value={a.id}>{a.name_en} ({a.level})</option>)}
          </select>
        </label>
        <label className="field">For (hours)<input className="input" type="number" min={0.5} max={72} step={0.5} value={f.hours} onChange={(e) => setF({ ...f, hours: e.target.value })} /></label>
      </div>
      <label className="field" style={{ marginTop: 10 }}>Reason / case number (logged)<input className="input" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></label>
    </Modal>
  )
}

function ResultCard({ d, onMap, onIncident, onLookout }) {
  const when = parseTs(d.ts)
  return (
    <li className="vs-card">
      {d.crop_url ? <img src={d.crop_url} alt={`Vehicle at ${d.camera_name}`} loading="lazy" /> : <span className="vs-noimg"><Icons.vehicle /></span>}
      <div className="vs-body">
        <div className="wl-title">
          {d.plate ? <span className="plate-chip" lang="bn">{d.plate}</span> : <Badge tone="muted" size="sm">No plate read</Badge>}
          {d.similarity != null && <Badge tone="info" size="sm">{Math.round(d.similarity * 100)}% alike</Badge>}
          {d.matched && <Badge tone="danger" size="sm" icon={Icons.alert}>Watchlist hit</Badge>}
        </div>
        <div className="meta">
          {[d.color && `${d.color}${d.color_reliable ? '' : ' (night)'}`, d.make_model, d.vehicle_type].filter(Boolean).join(' · ') || 'Attributes unknown'}
          {d.confidences?.color != null && <span className="muted"> · colour {pct(d.confidences.color)}</span>}
        </div>
        <div className="meta"><Icons.camera /> {d.camera_name} · <time dateTime={d.ts} title={when?.toLocaleString()}>{timeAgo(d.ts)}</time>{d.direction && ` · heading ${d.direction}`}</div>
        <div className="vs-actions">
          {d.lat != null && <button type="button" className="btn btn-sm" onClick={() => onMap(d)}><Icons.map /> Map</button>}
          <button type="button" className="btn btn-sm" onClick={() => onIncident(d)}><Icons.incident /> Incident</button>
          <button type="button" className="btn btn-sm" onClick={() => onLookout(d)}><Icons.eye /> Lookout</button>
        </div>
      </div>
    </li>
  )
}

const REG_LABEL = {
  registered_owner: 'Registered owner', vehicle_class: 'Class', make: 'Make', model: 'Model', colour: 'Colour', year: 'Year',
  registration_valid_until: 'Registration valid until', fitness_valid_until: 'Fitness valid until',
  tax_token_valid_until: 'Tax token valid until',
}

/* Owner and registration from the vehicle registry (BRTA). Shown only when a registry is connected
   and the role may use it; each lookup needs a reason and a case number and is audit-logged. */
function RegistryLookup() {
  const [status, setStatus] = useState(null)
  const [f, setF] = useState({ plate: '', reason: '', caseRef: '' })
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  useEffect(() => { fetchRegistryStatus().then(setStatus).catch(() => setStatus(null)) }, [])
  if (!status?.configured || !status.allowed) return null
  const go = async (e) => {
    e.preventDefault()
    setBusy(true); setErr(''); setRes(null)
    try { setRes(await registryLookup(f.plate.trim(), f.reason.trim(), f.caseRef.trim())) } catch (x) { setErr(x.message || 'Lookup failed') } finally { setBusy(false) }
  }
  const ready = f.plate.trim().length >= 3 && f.reason.trim().length >= 10 && f.caseRef.trim().length >= 3
  return (
    <Card title="Registration lookup (BRTA)" sub="Owner and papers of a plate, for an open case. Reason and case number are logged; the answer is not stored" className="mb">
      <form className="vs-reg" onSubmit={go}>
        <label className="field">Plate<input className="input" lang="bn" value={f.plate} onChange={(e) => setF({ ...f, plate: e.target.value })} placeholder="ঢাকা মেট্রো-গ ১১-২২৩৩" /></label>
        <label className="field">Case / GD / FIR number<input className="input" value={f.caseRef} onChange={(e) => setF({ ...f, caseRef: e.target.value })} placeholder="Gulshan GD 1234/26" /></label>
        <label className="field vs-reg-wide">Reason (at least 10 characters)<input className="input" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="Vehicle seen leaving the robbery scene" /></label>
        <div><button type="submit" className="btn btn-primary" disabled={!ready || busy}>{busy ? 'Looking up…' : 'Look up'}</button></div>
      </form>
      {err && <p className="msg-err" role="alert">{err}</p>}
      {res && !res.found && <p className="muted" role="status">{res.plate} is not in the registry.</p>}
      {res?.found && (
        <dl className="vs-reg-out" aria-label={`Registry record for ${res.plate}`}>
          <dt>Plate</dt><dd className="plate-chip" lang="bn">{res.plate}</dd>
          {Object.entries(REG_LABEL).filter(([k]) => res.record[k] != null).map(([k, l]) => (<Fragment key={k}><dt>{l}</dt><dd>{String(res.record[k])}</dd></Fragment>))}
          {res.record.reported_stolen && <><dt>Status</dt><dd><Badge tone="danger" size="sm">Reported stolen</Badge></dd></>}
        </dl>
      )}
    </Card>
  )
}

export function VehicleSearch({ ctx }) {
  const { push: toast } = useToast()
  const [mode, setMode] = useState('attrs')
  const [cat, setCat] = useState({ type: [], color: [], model: [] })
  const [areas, setAreas] = useState([])
  const [lookouts, setLookouts] = useState([])
  const [q, setQ] = useState({ reason: '', plate: '', vehicle_type: [], color: [], make_model: '', jurisdiction_id: '', camera_id: '', date_from: '', date_to: '' })
  const [photo, setPhoto] = useState(null)
  const [res, setRes] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [lookoutSeed, setLookoutSeed] = useState(null)
  const cams = ctx?.cameras || []

  const loadLookouts = () => fetchLookouts().then(setLookouts).catch(() => {})
  useEffect(() => {
    fetchVehicleCatalog().then((rows) => {
      const by = { type: [], color: [], model: [], make: [] }
      rows.forEach((r) => by[r.kind]?.push(r))
      setCat(by)
    }).catch(() => {})
    fetchJurisdictions(false).then(setAreas).catch(() => {})
    loadLookouts()
  }, [])

  const run = async (e) => {
    e?.preventDefault()
    setBusy(true); setError('')
    try {
      if (mode === 'photo') {
        setRes(await searchVehiclesByPhoto(photo, q.reason.trim()))
      } else {
        setRes(await searchVehicles({
          reason: q.reason.trim(), plate: q.plate.trim(), vehicle_type: q.vehicle_type, color: q.color,
          make_model: q.make_model ? [q.make_model] : [], jurisdiction_id: q.jurisdiction_id, camera_id: q.camera_id ? [q.camera_id] : [],
          date_from: q.date_from ? `${q.date_from}T00:00:00` : '', date_to: q.date_to ? `${q.date_to}T23:59:59` : '',
        }))
      }
    } catch (err) {
      setError(err.message || 'Search failed')
    } finally {
      setBusy(false)
    }
  }
  const criteria = q.plate.trim() || q.vehicle_type.length || q.color.length || q.make_model || q.jurisdiction_id || q.camera_id
  const ready = q.reason.trim().length >= 5 && (mode === 'photo' ? !!photo : !!criteria)

  const toIncident = async (d) => {
    try {
      const inc = await createIncident({ title: `Vehicle ${d.plate || d.make_model || d.color || ''} seen at ${d.camera_name}`.trim(),
        description: `From Vehicle Search (${q.reason}). Detection #${d.id}.`, priority: 'high', incident_type: 'MANUAL',
        camera_id: d.camera_id, camera_location: d.camera_name, plate_number: d.plate_canonical?.slice(0, 20) || null })
      toast(`Incident ${inc.ticket_id} opened`, 'ok')
    } catch (err) {
      toast(err.message || 'Could not open incident', 'danger')
    }
  }

  return (
    <div className="vs">
      <RegistryLookup />
      <Card title="Search vehicles" sub="Only the retention period is searchable. Every search is logged with its reason." className="mb">
        <form onSubmit={run} className="vs-form">
          <Seg value={mode} onChange={(m) => { setMode(m); setRes(null) }} options={[{ value: 'attrs', label: 'By plate / attributes' }, { value: 'photo', label: 'By photo' }]} />
          <label className="field">Reason / case number (required)<input className="input" value={q.reason} onChange={(e) => setQ({ ...q, reason: e.target.value })} placeholder="Gulshan FIR 77/2026 — tracing stolen Axio" /></label>
          {mode === 'attrs' ? (
            <>
              <div className="settings-grid">
                <label className="field">Plate (part is enough: “3456”, “গ ১২”)<input className="input plate-field" value={q.plate} onChange={(e) => setQ({ ...q, plate: e.target.value })} /></label>
                <label className="field">Make / model
                  <select className="input" value={q.make_model} onChange={(e) => setQ({ ...q, make_model: e.target.value })}>
                    <option value="">Any</option>{cat.model.map((m) => <option key={m.code} value={m.code}>{m.name_en}</option>)}
                  </select>
                </label>
                <label className="field">Area
                  <select className="input" value={q.jurisdiction_id} onChange={(e) => setQ({ ...q, jurisdiction_id: e.target.value })}>
                    <option value="">Anywhere</option>{areas.map((a) => <option key={a.id} value={a.id}>{a.name_en} ({a.level})</option>)}
                  </select>
                </label>
                <label className="field">Camera
                  <select className="input" value={q.camera_id} onChange={(e) => setQ({ ...q, camera_id: e.target.value })}>
                    <option value="">Any</option>{cams.map((c) => <option key={c.camera_id} value={c.camera_id}>{c.name || c.camera_id}</option>)}
                  </select>
                </label>
                <label className="field">From<input className="input" type="date" value={q.date_from} onChange={(e) => setQ({ ...q, date_from: e.target.value })} /></label>
                <label className="field">To<input className="input" type="date" value={q.date_to} onChange={(e) => setQ({ ...q, date_to: e.target.value })} /></label>
              </div>
              <Chips label="Type" options={cat.type} value={q.vehicle_type} onChange={(v) => setQ({ ...q, vehicle_type: v })} />
              <Chips label="Colour" options={cat.color} value={q.color} onChange={(v) => setQ({ ...q, color: v })} />
            </>
          ) : (
            <label className="field">Vehicle photo (searches the last 3 days by appearance)<input className="input" type="file" accept="image/*" onChange={(e) => setPhoto(e.target.files[0] || null)} /></label>
          )}
          <div className="ds-toolbar">
            <button type="submit" className="btn btn-primary" disabled={!ready || busy}><Icons.search /> {busy ? 'Searching…' : 'Search'}</button>
            {!ready && !busy && (
              <span className="meta">
                {q.reason.trim().length < 5 ? 'Enter the reason or case number first (it is logged).'
                  : mode === 'photo' ? 'Choose a vehicle photo.' : 'Add a plate or pick at least one type, colour, model, area or camera.'}
              </span>
            )}
            {mode === 'attrs' && criteria && <button type="button" className="btn" onClick={() => setLookoutSeed({ reason: q.reason, plate: q.plate, vehicle_type: q.vehicle_type[0], color: q.color[0], make_model: q.make_model, jurisdiction_id: q.jurisdiction_id })}><Icons.eye /> Start lookout with these</button>}
          </div>
        </form>
      </Card>

      {lookouts.length > 0 && (
        <Card title="Active lookouts" className="mb">
          <ul className="wl-list">
            {lookouts.map((b) => (
              <li key={b.ref} className="wl-item">
                <div className="wl-main">
                  <div className="wl-title"><b className="mono">{b.ref}</b><Badge tone="orange" size="sm" icon={Icons.eye}>{b.cameras.length} camera(s)</Badge><Badge tone="muted" size="sm">{b.origin}</Badge></div>
                  <div className="meta">{Object.values(b.payload).join(' · ') || b.target_ref} — until {parseTs(b.window_end)?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}{b.reason && ` · ${b.reason}`}</div>
                </div>
                <div className="wl-actions"><button type="button" className="btn btn-sm" onClick={async () => { await cancelLookout(b.ref); toast(`Lookout ${b.ref} ended`, 'ok'); loadLookouts() }}>End</button></div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {busy && <SkeletonList rows={4} label="Searching" />}
      {error && <ErrorState message={error} onRetry={run} />}
      {res && !busy && (
        <Card title="Results" sub={res.total != null ? `${res.total} detection(s)` : `${res.items.length} most similar`} flush>
          {res.items.length === 0
            ? <EmptyState icon={Icons.search} title="Nothing found">Widen the time range, drop a criterion, or try part of the plate.</EmptyState>
            : <ul className="vs-grid">{res.items.map((d) => (
                <ResultCard key={d.id} d={d} onMap={(x) => ctx?.showOnMap?.({ camera_id: x.camera_id, lat: x.lat, lng: x.lng })}
                  onIncident={toIncident} onLookout={(x) => setLookoutSeed({ reason: q.reason, plate: x.plate, vehicle_type: x.vehicle_type, color: x.color, make_model: x.make_model, camera_ids: [x.camera_id] })} />
              ))}</ul>}
        </Card>
      )}
      {lookoutSeed && <LookoutDialog seed={lookoutSeed} areas={areas} onClose={() => setLookoutSeed(null)} onDone={loadLookouts} />}
    </div>
  )
}
