/* Find a person in this incident's photos and videos by clothing colour ("red top, blue trousers").
   Only this case's evidence is searched, and each search is audit-logged. Colours shift with light:
   a match is a lead to look at, not an identification. */
import { useState } from 'react'
import { Icons } from './ui'
import { EmptyState, ErrorState } from './ds'
import { API_BASE, searchEvidenceAppearance } from '../services/api'

const COLOURS = ['black', 'white', 'grey', 'silver', 'red', 'maroon', 'orange', 'brown', 'yellow', 'green', 'blue']
const SWATCH = { black: '#111', white: '#f4f4f4', grey: '#888', silver: '#c0c0c0', red: '#d33', maroon: '#7a1f1f', orange: '#f08a24', brown: '#7b4a26', yellow: '#f2d22e', green: '#2f9e44', blue: '#2862c9' }
const at = (s) => (s == null ? 'photo' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')} in video`)

function ColourPick({ label, value, onChange }) {
  return (
    <fieldset className="cs-pick">
      <legend>{label}</legend>
      <button type="button" className={`cs-sw any ${!value ? 'on' : ''}`} aria-pressed={!value} onClick={() => onChange('')}>Any</button>
      {COLOURS.map((c) => (
        <button key={c} type="button" className={`cs-sw ${value === c ? 'on' : ''}`} aria-pressed={value === c} title={c} aria-label={c}
          style={{ '--sw': SWATCH[c] }} onClick={() => onChange(value === c ? '' : c)} />
      ))}
    </fieldset>
  )
}

export function ClothingSearch({ incidentId }) {
  const [upper, setUpper] = useState('')
  const [lower, setLower] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const go = async () => {
    setBusy(true); setErr('')
    try { setRes(await searchEvidenceAppearance(incidentId, upper, lower)) } catch (e) { setErr(e.message || 'Search failed') } finally { setBusy(false) }
  }
  return (
    <div className="cs">
      <div className="cs-row">
        <ColourPick label="Top" value={upper} onChange={setUpper} />
        <ColourPick label="Trousers / lower" value={lower} onChange={setLower} />
        <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={go}><Icons.search /> {busy ? 'Searching…' : 'Find in evidence'}</button>
      </div>
      {err && <ErrorState compact message={err} onRetry={go} />}
      {res && res.summary.people === 0 && (
        <EmptyState compact icon={Icons.users} title="No people indexed in this case yet">
          {res.indexing ? 'People in photos and videos are indexed a few seconds after upload.' : 'Clothing search is switched off on this server (APPEARANCE_INDEX).'}
        </EmptyState>
      )}
      {res && res.summary.people > 0 && (
        <>
          <p className="meta">{res.results.length} of {res.summary.people} people seen in this case's evidence match. Colours change with light: check each one.</p>
          <ul className="cs-grid">
            {res.results.map((p) => (
              <li key={p.id}>
                <a href={`${API_BASE}/evidence-items/${encodeURIComponent(p.ref)}/file`} target="_blank" rel="noreferrer" title={`Open ${p.ref}`}>
                  <img src={`${API_BASE}/evidence-appearance/${p.id}/crop`} alt={`Person in ${p.ref}: ${p.upper || '?'} top, ${p.lower || '?'} lower`} loading="lazy" />
                </a>
                <span className="mono">{p.ref}</span>
                <span className="muted">{at(p.t_seconds)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
