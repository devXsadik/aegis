/* Identification breakdown on an alert: what the camera read vs what the watchlist says,
   per attribute ✓ / ✗, confidences, overall score, direction. Operators confirm or reject. */
import { Icons } from './ui'
import { Badge } from './ds'

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
    </section>
  )
}
