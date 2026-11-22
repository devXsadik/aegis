/* One camera kept in view while working on other pages: a small live picture in the corner.
   Pinned from a tile on the Live page; remembered on this device; hidden on Live itself. */
import { useState } from 'react'
import { Icons } from './ui'
import { liveStreamUrl } from '../services/api'

export function PinnedCamera({ cam, onOpen, onClose }) {
  const [failed, setFailed] = useState(false)
  const [small, setSmall] = useState(false)
  const live = cam.status === 'live' && !failed
  const hot = cam.threat_score >= 40 || cam.flags?.length > 0
  return (
    <aside className={`pip ${small ? 'small' : ''} ${hot ? 'hot' : ''}`} aria-label={`Pinned camera: ${cam.name}`}>
      <div className="pip-bar">
        <span className={`status-dot ${live ? 'ok' : ''}`} />
        <b title={cam.name}>{cam.name}</b>
        <button type="button" className="pip-btn" title={small ? 'Larger' : 'Smaller'} aria-label={small ? 'Make larger' : 'Make smaller'}
          onClick={() => setSmall(!small)}>{small ? '▢' : '–'}</button>
        <button type="button" className="pip-btn" title="Open on Live cameras" aria-label="Open on Live cameras" onClick={onOpen}><Icons.live /></button>
        <button type="button" className="pip-btn" title="Unpin" aria-label="Unpin camera" onClick={onClose}><Icons.close /></button>
      </div>
      {!small && (
        <button type="button" className="pip-view" onClick={onOpen} aria-label={`Open ${cam.name} on Live cameras`}>
          {live
            ? <img src={liveStreamUrl(cam.camera_id)} alt="" onError={() => { setFailed(true); setTimeout(() => setFailed(false), 5000) }} />
            : <span className="pip-wait"><Icons.camera />{cam.status === 'off' ? 'Paused' : 'No video'}</span>}
        </button>
      )}
    </aside>
  )
}
