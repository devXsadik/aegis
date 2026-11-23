/* Identification breakdown on an alert: what the camera read vs what the watchlist says,
   per attribute ✓ / ✗, confidences, overall score, direction. Operators confirm or reject. */
import { useEffect, useState } from 'react'
import { Icons } from './ui'
import { Badge } from './ds'
import { addCorrection, fetchVehicleCatalog } from '../services/api'
import { useToast } from './Toast'

const RESULT = {
  match: { sym: '✓', tone: 'ok', label: 'matches' },
  mismatch: { sym: '✗', tone: 'danger', label: 'differs' },
  unknown: { sym: '?', tone: 'muted', label: 'not known' },
  unreliable: { sym: '~', tone: 'warn', label: 'unreliable at night' },
}
const LEVEL_TONE = { confirmed: 'danger', plate_mismatch: 'orange', probable: 'orange', possible: 'warn', candidate: 'info' }
const NAMES = { type: 'Type', color: 'Colour', model: 'Make / model', reid: 'Appearance (re-ID)' }
const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)

export function VehicleMatchCard({ id }) {
  const m = id.match
  const w = id.watch || {}
  const read = id.read || {}
  return (
    <section className="match-card" aria-label="Vehicle match details">
      <header className="match-head">
        <Badge tone={LEVEL_TONE[m.level] || 'muted'} icon={Icons.vehicle}>{m.label}</Badge>
        <span className="match-score" title="Combined match score">Score <b>{Math.round(m.score * 100)}</b>/100</span>
        {id.direction && <Badge tone="cyan" icon={Icons.map} size="sm">Moving {id.direction}</Badge>}
        {id.night && <Badge tone="warn" size="sm">Night / IR — colour down-weighted</Badge>}
        {id.bolo && <Badge tone="info" size="sm" icon={Icons.eye}>Lookout {id.bolo}</Badge>}
      </header>
      <div className="match-plates">
        {id.crop_url && <img className="match-crop" src={id.crop_url} alt="Vehicle seen by the camera" />}
        <div className="match-plate-col">
          <span className="muted">Read by camera</span>
          <span className="plate-chip" lang="bn">{read.plate_text || 'Not read'}</span>
          <span className="muted mono">{pct(id.confidences?.plate)} sure</span>
        </div>
        <span className={`match-vs plate-${m.plate}`} aria-label={`Plate ${m.plate}`}>{m.plate === 'exact' ? '=' : m.plate === 'fuzzy' ? '≈' : '≠'}</span>
        <div className="match-plate-col">
          <span className="muted">Watchlist {w.ref || ''}</span>
          <span className="plate-chip" lang="bn">{w.plate || 'No plate listed'}</span>
          {w.case_no && <span className="muted mono">{w.case_no}</span>}
        </div>
      </div>
      <table className="table match-table">
        <thead><tr><th scope="col">Attribute</th><th scope="col">Watchlist</th><th scope="col">Seen</th><th scope="col">Sure</th><th scope="col">Result</th></tr></thead>
        <tbody>
          {m.checks.map((c) => {
            const r = RESULT[c.result] || RESULT.unknown
            return (
              <tr key={c.attribute}>
                <th scope="row">{NAMES[c.attribute] || c.attribute}</th>
                <td>{c.listed || '—'}</td>
                <td>{c.seen || '—'}</td>
                <td>{pct(c.confidence)}</td>
                <td><span className={`match-sym tone-${r.tone}`} aria-label={r.label} title={r.label}>{r.sym}</span></td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="ds-setting-hint" style={{ margin: 0 }}>
        Possible match — needs verification. Confirm only after checking the image against the watchlist entry; rejections improve the models.
      </p>
      {id.detection_id && <Correct detectionId={id.detection_id} />}
    </section>
  )
}

const FIELD_KIND = { vehicle_type: 'type', color: 'color', make_model: 'model' }

/** "The camera got the colour wrong": the crop and the right answer go to the review queue. */
function Correct({ detectionId }) {
  const { push: toast } = useToast()
  const [open, setOpen] = useState(false)
  const [cat, setCat] = useState({})
  const [field, setField] = useState('color')
  const [value, setValue] = useState('')
  useEffect(() => {
    if (!open || cat.color) return
    fetchVehicleCatalog().then((rows) => {
      const by = {}
      rows.forEach((r) => { (by[r.kind] = by[r.kind] || []).push(r) })
      setCat(by)
    }).catch(() => {})
  }, [open, cat.color])
  if (!open) return <button type="button" className="link-btn" onClick={() => setOpen(true)}>Wrong type, colour or model? Correct it</button>
  const send = async () => {
    try {
      await addCorrection(detectionId, field, value)
      toast('Thanks — sent to the review queue for the next training round', 'ok')
      setOpen(false)
    } catch (e) {
      toast(e.message || 'Could not send', 'danger')
    }
  }
  return (
    <div className="ds-toolbar">
      <select className="input" value={field} onChange={(e) => { setField(e.target.value); setValue('') }} aria-label="Attribute to correct">
        <option value="color">Colour</option><option value="vehicle_type">Type</option><option value="make_model">Make / model</option>
      </select>
      <select className="input" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Correct value">
        <option value="">Correct value…</option>{(cat[FIELD_KIND[field]] || []).map((c) => <option key={c.code} value={c.code}>{c.name_en}</option>)}
      </select>
      <button type="button" className="btn btn-sm btn-primary" disabled={!value} onClick={send}>Send correction</button>
    </div>
  )
}

/** Live face beside the watchlist photos, with the similarity against both thresholds. */
export function FaceMatchCard({ id }) {
  const f = id.face
  const pctSim = Math.round(f.similarity * 100)
  return (
    <section className="match-card" aria-label="Face match details">
      <header className="match-head">
        <Badge tone={f.similarity >= f.alert_threshold ? 'danger' : 'warn'} icon={Icons.watchlist}>Possible match — needs verification</Badge>
        <span className="match-score">Similarity <b>{pctSim}%</b></span>
        {f.risk_level && <Badge tone="orange" size="sm">Risk: {f.risk_level}</Badge>}
        {f.case_no && <Badge tone="muted" size="sm">{f.case_no}</Badge>}
      </header>
      <div className="face-compare">
        <figure>
          {f.crop_url ? <img src={f.crop_url} alt="Face seen by the camera" /> : <span className="face-missing">No live crop</span>}
          <figcaption>Live</figcaption>
        </figure>
        <div className="face-photos">
          {f.watch_photos.map((u, i) => (
            <figure key={u}><img src={u} alt={`Watchlist photo ${i + 1} of ${f.name}`} /><figcaption>{i === 0 ? f.name : ''}</figcaption></figure>
          ))}
        </div>
      </div>
      <div className="sim-bar" role="img" aria-label={`Similarity ${pctSim}%, possible from ${Math.round(f.possible_threshold * 100)}%, alert from ${Math.round(f.alert_threshold * 100)}%`}>
        <span className="sim-fill" style={{ width: `${Math.max(0, Math.min(100, pctSim))}%` }} />
        <span className="sim-mark" style={{ left: `${f.possible_threshold * 100}%` }} title="Possible match threshold" />
        <span className="sim-mark alert" style={{ left: `${f.alert_threshold * 100}%` }} title="Alert threshold" />
      </div>
      {f.others?.length > 0 && <p className="ds-setting-hint" style={{ margin: 0 }}>Next closest: {f.others.map((o) => `${o.person_id} (${Math.round(o.similarity * 100)}%)`).join(', ')}</p>}
      <p className="ds-setting-hint" style={{ margin: 0 }}>Model {f.model} · face quality {Math.round((f.quality ?? 0) * 100)}%. Confirm only if you are sure it is the same person; rejections are kept to measure false alarms.</p>
    </section>
  )
}
