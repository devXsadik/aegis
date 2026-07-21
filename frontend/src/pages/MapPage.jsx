import { Card, Icons, Tag, Empty, timeAgo, SEVERITY_TONE } from '../components/ui'
import { MapPin } from '../components/MapPin'

export function MapPage({ ctx }) {
  const { mapCameras, mapEvents } = ctx
  const withGps = mapCameras.filter((c) => c.lat != null && c.lng != null)
  const primary = withGps[0]

  return (
    <div className="grid grid-23">
      <Card title="GIS Camera Map" sub={`${withGps.length} geolocated cameras`}>
        {primary ? (
          <>
            <MapPin lat={primary.lat} lng={primary.lng} label={primary.name || primary.location} height={340} />
            <div className="map-legend">
              <span className="key"><span className="swatch" style={{ background: 'var(--ok)' }} /> Camera online</span>
              <span className="key"><span className="swatch" style={{ background: 'var(--danger)' }} /> Threat location</span>
              <span className="key"><span className="swatch" style={{ background: 'var(--primary)' }} /> Police station</span>
              <span className="key"><span className="swatch" style={{ background: 'var(--warn)' }} /> Restricted zone</span>
            </div>
          </>
        ) : (
          <Empty icon={Icons.map}>No camera GPS configured. Run <code>python scripts/seed_cameras.py</code></Empty>
        )}
      </Card>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Card title="Cameras" sub="status & coordinates">
          {withGps.length === 0 && <Empty icon={Icons.camera}>No cameras registered</Empty>}
          {withGps.map((cam) => (
            <div key={cam.camera_id} className="row">
              <div>
                <b>{cam.name || cam.camera_id}</b>
                <div className="meta">{cam.location}</div>
                <div className="meta mono">{cam.lat?.toFixed(5)}, {cam.lng?.toFixed(5)}</div>
              </div>
              <Tag tone={cam.active ? 'ok' : 'warn'}>{cam.active ? 'Online' : 'Offline'}</Tag>
            </div>
          ))}
        </Card>
        <Card title="Detections on Map" sub="last 24h">
          {(!mapEvents || mapEvents.length === 0) && <Empty icon={Icons.eye}>No geolocated detections yet</Empty>}
          {(mapEvents || []).slice(0, 8).map((ev, i) => (
            <div key={i} className="row">
              <div>
                <b>{ev.description || ev.event_type}</b>
                <div className="meta">{ev.camera_name} · {timeAgo(ev.timestamp)}</div>
              </div>
              <Tag tone={SEVERITY_TONE[ev.severity] || 'info'}>{ev.severity || 'info'}</Tag>
            </div>
          ))}
        </Card>
      </div>
    </div>
  )
}
