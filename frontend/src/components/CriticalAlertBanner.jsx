import { useEffect, useRef } from 'react'

const AUTO_HIDE_MS = 30000

// The backend message also carries GPS and a map link; the card shows those as separate fields.
const headline = (m) => (m || '').split(' — GPS')[0].split(' | ')[0]

export function CriticalAlertBanner({ alert, onDismiss, onViewMap, onOpenAlerts }) {
  const dismissRef = useRef(onDismiss)
  dismissRef.current = onDismiss                            // parent re-renders must not restart the timer
  useEffect(() => {
    if (!alert) return undefined
    const t = setTimeout(() => dismissRef.current?.(), AUTO_HIDE_MS)   // a new alert restarts this
    return () => clearTimeout(t)
  }, [alert])

  if (!alert) return null
  const hasGps = alert.lat != null && alert.lng != null
  const officers = alert.assignedOfficers || []

  return (
    <div className="critical-alert-banner" role="alert" aria-live="assertive">
      <div className="critical-head">
        <span aria-hidden="true">🚨</span>
        <strong>{alert.type?.replace(/_/g, ' ')}</strong>
        <button className="critical-x" onClick={onDismiss} aria-label="Dismiss alert">×</button>
      </div>
      <div className="critical-body">
        <div className="critical-title">{headline(alert.message)}</div>
        <dl className="critical-grid">
          <dt>Camera</dt><dd>{alert.cameraName || alert.camera}{alert.cameraId ? ` (${alert.cameraId})` : ''}</dd>
          {hasGps && (<><dt>GPS</dt><dd className="mono">{Number(alert.lat).toFixed(5)}, {Number(alert.lng).toFixed(5)}</dd></>)}
          <dt>Officer</dt>
          <dd>{officers.length ? `${officers.map((o) => o.name).join(', ')} alerted` : 'None assigned to this camera'}</dd>
        </dl>
      </div>
      <div className="critical-actions">
        {onOpenAlerts && <button className="btn btn-sm btn-primary" onClick={onOpenAlerts}>Review</button>}
        {hasGps && onViewMap && <button className="btn btn-sm" onClick={onViewMap}>View on map</button>}
      </div>
    </div>
  )
}
