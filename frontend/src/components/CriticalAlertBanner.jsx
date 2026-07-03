import { MapPin } from './MapPin'

export function CriticalAlertBanner({ alert, onDismiss }) {
  if (!alert) return null

  return (
    <div className="critical-alert-banner" role="alert">
      <div className="critical-alert-content">
        <span className="critical-alert-icon">🚨</span>
        <div>
          <strong>{alert.type?.replace(/_/g, ' ')}</strong>
          <p>{alert.message}</p>
          <p className="critical-alert-camera">
            Camera: {alert.cameraName || alert.camera} {alert.cameraId ? `(${alert.cameraId})` : ''}
          </p>
          {alert.lat != null && alert.lng != null && (
            <p className="critical-alert-gps">
              GPS: {Number(alert.lat).toFixed(5)}, {Number(alert.lng).toFixed(5)}
            </p>
          )}
        </div>
      </div>
      <button className="critical-dismiss" onClick={onDismiss}>Dismiss</button>
      {alert.lat != null && alert.lng != null && (
        <div className="critical-alert-map">
          <MapPin
            lat={alert.lat}
            lng={alert.lng}
            label={`Detection at ${alert.cameraName || alert.camera}`}
            height={180}
          />
        </div>
      )}
    </div>
  )
}
