import { MapPin } from './MapPin'

export function CameraMapOverview({ cameras, events }) {
  const withGps = (cameras || []).filter((c) => c.lat != null && c.lng != null)
  const primary = withGps[0]

  if (!primary) {
    return <p className="empty-state">No camera GPS configured. Run <code>python scripts/seed_cameras.py</code></p>
  }

  return (
    <div>
      <MapPin lat={primary.lat} lng={primary.lng} label={primary.name || primary.location} height={280} />
      <div className="map-camera-list">
        <h4>All Cameras ({withGps.length})</h4>
        {withGps.map((cam) => (
          <div key={cam.camera_id} className="camera-row">
            <div>
              <strong>{cam.name}</strong> — {cam.location}
              <div className="event-gps">{cam.lat?.toFixed(5)}, {cam.lng?.toFixed(5)}</div>
            </div>
            <span className={`status-badge ${cam.active ? 'status-active' : 'status-warn'}`}>
              {cam.active ? 'Active' : 'Off'}
            </span>
          </div>
        ))}
      </div>
      {events?.length > 0 && (
        <div className="map-events-list">
          <h4>Recent Detections on Map</h4>
          {events.slice(0, 8).map((ev, i) => (
            <div key={i} className="log-entry">
              <span>{ev.description} @ {ev.camera_name}</span>
              <span className={`status-badge ${ev.severity === 'high' ? 'status-alert' : 'status-active'}`}>
                {ev.severity}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
