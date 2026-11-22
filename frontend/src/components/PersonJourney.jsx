/* "Where was this person?" — every sighting of one person across cameras, as visits in time
   order: face matches, look-alike tracking (clothing and build) and capture stills. */
import { useEffect, useState } from 'react'
import { Empty, Icons, Modal, Seg } from './ui'
import { captureImageUrl, evidenceImageUrl, fetchPersonJourney } from '../services/api'
import { parseTs } from '../lib/time'
import { waitLabel } from '../lib/events'

const RANGES = [{ value: 24, label: '24 h' }, { value: 72, label: '3 days' }, { value: 168, label: '7 days' }]
const time = (ts) => parseTs(ts)?.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }) || ''
const secs = (a, b) => ((parseTs(b)?.getTime() || 0) - (parseTs(a)?.getTime() || 0)) / 1000

function Thumb({ image }) {
  if (!image) return <span className="pj-thumb empty"><Icons.users /></span>
  const src = image.kind === 'capture' ? captureImageUrl(image.id, 160) : evidenceImageUrl(image.id, 'roi')
  return <img className="pj-thumb" src={src} alt="" loading="lazy" />
}

export function PersonJourney({ name, onClose, onShowOnMap }) {
  const [hours, setHours] = useState(72)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    fetchPersonJourney(name, hours)
      .then((d) => { if (alive) { setData(d); setError('') } })
      .catch((e) => { if (alive) setError(e.message || 'Could not load sightings') })
    return () => { alive = false }
  }, [name, hours])

  const visits = data?.visits || []
  return (
    <Modal title={`Where was ${name}?`} onClose={onClose} className="pj-modal">
      <div className="pj-head">
        <span className="meta">
          {data ? `${data.sightings} sighting${data.sightings === 1 ? '' : 's'} on ${data.cameras.length} camera${data.cameras.length === 1 ? '' : 's'}` : 'Loading…'}
        </span>
        <Seg value={hours} onChange={setHours} options={RANGES} />
      </div>
      {error && <p className="login-error" role="alert">{error}</p>}
      {data && visits.length === 0 && <Empty icon={Icons.map}>Not seen by any camera in this period.</Empty>}
      <ol className="pj-list">
        {visits.map((v, i) => {
          const stayed = secs(v.from, v.to)
          const gap = i > 0 ? secs(visits[i - 1].to, v.from) : null
          return (
            <li key={`${v.camera_id}-${v.from}`}>
              {gap != null && (
                <div className="pj-hop">
                  {visits[i - 1].camera_id === v.camera_id ? 'Back on the same camera' : `Moved from ${visits[i - 1].camera}`} · {waitLabel(gap)} later
                </div>
              )}
              <div className="pj-visit">
                <Thumb image={v.image} />
                <div className="pj-body">
                  <b>{v.camera}</b>
                  <span className="meta">{time(v.from)}{stayed >= 60 ? ` · for ${waitLabel(stayed)}` : ''} · {v.count} sighting{v.count === 1 ? '' : 's'}</span>
                  <span className="pj-tags">{v.sources.map((s) => <span key={s} className={`pj-src ${s.startsWith('Look') ? 'warn' : ''}`}>{s}</span>)}</span>
                </div>
                {onShowOnMap && v.lat != null && (
                  <button type="button" className="btn btn-sm" onClick={() => onShowOnMap(v)}><Icons.map /> Map</button>
                )}
              </div>
            </li>
          )
        })}
      </ol>
      {visits.some((v) => v.sources.some((s) => s.startsWith('Look'))) && (
        <p className="meta pj-note">Look-alike sightings match clothing and build, not the face: check the stills before acting on them.</p>
      )}
    </Modal>
  )
}
