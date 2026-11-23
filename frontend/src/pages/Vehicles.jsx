import { Card, Icons, Tag, Empty, timeAgo } from '../components/ui'
import { VehicleWatchlist } from '../components/WatchlistAdmin'

export function Vehicles({ ctx }) {
  const { vehicleDetections, me } = ctx
  return (
    <div className="stack-page">
      <VehicleWatchlist role={me?.role} />
      <Card title="Plates read recently" sub="Number plates the cameras read (ANPR)" flush>
        {(!vehicleDetections || vehicleDetections.length === 0) ? (
          <div style={{ padding: 16 }}>
            <Empty icon={Icons.vehicle}>No plates read yet. Plates appear here once detection is running on a camera that sees traffic.</Empty>
          </div>
        ) : (
          <div className="table-wrap table-stack">
            <table className="table">
              <thead><tr><th scope="col">Plate</th><th scope="col">Camera</th><th scope="col">Time</th><th scope="col">Status</th></tr></thead>
              <tbody>
                {vehicleDetections.map((v, i) => (
                  <tr key={v.id || i}>
                    <td className="mono cell-wide"><b>{v.plate_number || '—'}</b></td>
                    <td data-label="Camera">{v.camera_location || v.camera_id || '—'}</td>
                    <td data-label="Time" className="muted">{timeAgo(v.timestamp)}</td>
                    <td data-label="Status"><Tag tone={v.is_suspicious ? 'danger' : 'ok'}>{v.is_suspicious ? 'Watchlisted' : 'Clear'}</Tag></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
