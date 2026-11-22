import { useCallback, useEffect, useRef, useState } from 'react'
import { acknowledgeAlert } from '../services/api'
import { useWebSocket } from './useWebSocket'
import { useAutoAlerts } from './useAutoAlerts'
import { can } from '../lib/permissions'
import { formatEvent } from '../lib/events'

const MUTE_MS = 10 * 60 * 1000
// One card per (type, camera, person): two cameras alerting at once must both stay on screen.
export const alertKey = (a) => `${a.type}|${a.cameraId ?? a.camera}|${a.personName ?? ''}`

/** The alerts socket: every event joins the feed; critical ones pop up and ring, unless the
    camera is muted (for 10 min, from the pop-up) or, for police, the camera is someone else's. */
export function useCriticalAlerts({ authed, me, page, nowTick, setEvents, onFocusMap, toast }) {
  const [criticalAlerts, setCriticalAlerts] = useState([])
  const [captureEvent, setCaptureEvent] = useState(null)      // newest capture-basket still
  const dropCritical = (key) => setCriticalAlerts((list) => list.filter((a) => alertKey(a) !== key))

  // A camera that keeps firing on something known (a guard, a poster) can be muted for a while:
  // its alerts still reach the queue and the badge, they just stop popping up and ringing.
  const [muted, setMuted] = useState(() => {
    try { return JSON.parse(localStorage.getItem('aegis_muted_cams') || '{}') } catch { return {} }
  })
  const saveMuted = (next) => {
    setMuted(next)
    try { localStorage.setItem('aegis_muted_cams', JSON.stringify(next)) } catch { /* ignore */ }
  }
  const activeMuted = Object.fromEntries(Object.entries(muted).filter(([, m]) => m.until > nowTick))
  const muteCamera = (alert, now) => {
    const id = alert.cameraId ?? alert.camera
    saveMuted({ ...activeMuted, [id]: { until: now + MUTE_MS, name: alert.cameraName || alert.camera || id } })
    setCriticalAlerts((list) => list.filter((a) => (a.cameraId ?? a.camera) !== id))
    toast(`Pop-ups from ${alert.cameraName || alert.camera || id} muted for 10 minutes. Alerts still go to the queue.`, 'ok')
  }
  const mutedRef = useRef(muted)
  useEffect(() => { mutedRef.current = muted }, [muted])

  const { handleAlert } = useAutoAlerts((alert) => {
    setCriticalAlerts((list) => [alert, ...list.filter((a) => alertKey(a) !== alertKey(alert))].slice(0, 4))
    // If the operator is already looking at the map, take them to the camera that raised the alert.
    if (page === 'map' && alert.lat != null && alert.lng != null) onFocusMap(alert)
  })

  const onMessage = useCallback((data) => {
    if (data.alert_type === 'PIPELINE_HEARTBEAT') return
    // A still for the capture basket, not an alert: it must not ring or fill the event feed.
    if (data.alert_type === 'ALERT_CAPTURE') { if (data.capture) setCaptureEvent(data.capture); return }
    setEvents((prev) => [formatEvent(data), ...prev].slice(0, 200))
    // A police officer is only paged for cameras assigned to them (unassigned alerts reach everyone).
    const assigned = data.assigned_officers || data.data?.assigned_officers || []
    if (me?.role === 'police' && assigned.length && !assigned.some((o) => o.id === me.id)) return
    if ((mutedRef.current[data.camera_id ?? data.camera_location]?.until || 0) > Date.now()) return
    handleAlert(data)
  }, [handleAlert, me, setEvents])
  const { connected } = useWebSocket('alerts', onMessage, authed && can(me?.role, 'data.view'))

  const ackCritical = async (alert) => {
    try {
      await acknowledgeAlert(alert.alertId)
      dropCritical(alertKey(alert))
    } catch (e) {
      toast(e.message || 'Could not acknowledge', 'danger')
    }
  }

  return { criticalAlerts, dropCritical, ackCritical, muteCamera, activeMuted, unmuteAll: () => saveMuted({}), connected, captureEvent }
}
