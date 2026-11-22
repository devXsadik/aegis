import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchCameraDevices, fetchCameraPower, fetchStreamingCameras, fetchSystemStatus } from '../services/api'
import { useWebSocket } from './useWebSocket'
import { can } from '../lib/permissions'
import { buildCamList } from '../lib/cameras'

/** What the cameras and the pipeline are doing now. Heartbeats on the status socket update a
    camera at once; a 10 s poll picks up what they don't carry (offline cameras, model health,
    which cameras stream). Devices and power (on/off) are polled for roles that may switch them. */
export function useLiveStatus({ authed, role, cameras, reloadTick }) {
  const live = authed && can(role, 'data.view')
  const [systemStatus, setSystemStatus] = useState(null)
  const [streamingCams, setStreamingCams] = useState([])
  const [apiDown, setApiDown] = useState(false)

  const streamingRef = useRef(streamingCams)
  useEffect(() => { streamingRef.current = streamingCams }, [streamingCams])
  const lastStreamCheck = useRef(0)
  const onStatus = useCallback((data) => {
    if (data.alert_type !== 'PIPELINE_HEARTBEAT' || !data.camera_id) return
    const id = data.camera_id
    setSystemStatus((s) => s && {
      ...s,
      online: true,
      last_heartbeat: data.timestamp ?? s.last_heartbeat,
      cameras: {
        ...s.cameras,
        [id]: {
          ...s.cameras?.[id],
          camera_location: data.camera_location,
          fps: data.fps,
          threat_score: data.threat_score,
          flags: data.flags ?? s.cameras?.[id]?.flags ?? [],
          infer_ms: data.infer_ms,
          ai_age_s: data.ai_age_s,
          last_seen: data.timestamp,
          sla: 'ok',
        },
      },
    })
    // A camera that just came up: fetch the streaming list now rather than at the next poll.
    if (!streamingRef.current.includes(id) && Date.now() - lastStreamCheck.current > 5000) {
      lastStreamCheck.current = Date.now()
      fetchStreamingCameras().then((r) => setStreamingCams(r.cameras || [])).catch(() => {})
    }
  }, [])
  const { connected: statusConnected } = useWebSocket('status', onStatus, live)

  useEffect(() => {
    if (!live) return undefined
    let misses = 0
    const poll = () => {
      fetchSystemStatus().then((s) => { misses = 0; setApiDown(false); setSystemStatus(s) }).catch(() => {
        misses += 1
        if (misses >= 2) setApiDown(true)
      })
      fetchStreamingCameras().then((r) => setStreamingCams(r.cameras || [])).catch(() => {})
    }
    poll()
    const interval = setInterval(poll, 10000)
    return () => clearInterval(interval)
  }, [live, reloadTick])

  // Cameras plugged into this computer, and which cameras are switched on (shared by every view).
  const [devices, setDevices] = useState({ devices: [], unplugged: [] })
  const [power, setPower] = useState({})
  useEffect(() => {
    if (!authed || !can(role, 'camera.power')) return undefined    // operational roles only (403 otherwise)
    const load = () => {
      fetchCameraDevices().then(setDevices).catch(() => {})
      fetchCameraPower().then(setPower).catch(() => {})
    }
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [authed, role, cameras])

  const camList = useMemo(() => buildCamList(cameras, systemStatus, streamingCams, power, devices.unplugged),
    [cameras, systemStatus, streamingCams, power, devices.unplugged])

  return { systemStatus, streamingCams, apiDown, statusConnected, devices, power, setPower, camList }
}
