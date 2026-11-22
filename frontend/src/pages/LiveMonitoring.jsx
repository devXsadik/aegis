import { can } from '../lib/permissions'
import { buildCamList } from '../lib/cameras'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useToast } from '../components/Toast'
import { CaptureBasket } from '../components/CaptureBasket'
import { Card, Icons, Seg, Pill, Tag, Empty, timeAgo, useConfirm } from '../components/ui'
import {
  liveStreamUrl, setCameraPower,
  fetchVmsTimeline, fetchPtz, ptzMove, ptzStop, ptzHome, ptzSetMode,
  ptzSavePreset, ptzGotoPreset, openVmsPlayback,
} from '../services/api'

const STATUS = {
  live: { label: 'LIVE', tone: 'ok' },
  online: { label: 'NO VIDEO', tone: 'warn' },
  offline: { label: 'OFFLINE', tone: 'muted' },
  off: { label: 'PAUSED', tone: 'muted' },
}

// Red alerts in view right now, as reported by the camera itself.
const FLAG = { CRIMINAL_DETECTED: 'WATCHLIST', WEAPON_DETECTED: 'ARMED', PERSON_TRACKED: 'TRACKING' }

export const ExpandIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" />
  </svg>
)
const Chevron = ({ dir }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
    style={{ transform: `rotate(${{ up: 0, right: 90, down: 180, left: 270 }[dir]}deg)` }}>
    <path d="M6 15l6-6 6 6" />
  </svg>
)

const PinIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 17v5M8 3h8l-1 6 3 3v2H6v-2l3-3-1-6z" />
  </svg>
)

const PowerIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v9M6.3 7.2a8 8 0 1 0 11.4 0" />
  </svg>
)

const HomeIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 11l9-8 9 8M5 10v10h14V10" />
  </svg>
)

function CamFeed({ cam, objectFit = 'cover', starting = false, onPower }) {
  const [failed, setFailed] = useState(false)
  const showVideo = cam.status === 'live' && !failed
  const st = STATUS[showVideo ? 'live' : (cam.status === 'live' ? 'online' : cam.status)]

  return (
    <>
      {showVideo && (
        <img className="cam-video" src={liveStreamUrl(cam.camera_id)} alt={cam.name}
          style={{ objectFit }} onError={() => { setFailed(true); setTimeout(() => setFailed(false), 5000) }} />
      )}
      {!showVideo && (
        <div className="cam-offline">
          <Icons.camera />
          <b>
            {cam.status === 'off' ? 'Camera is paused'
              : starting ? 'Starting camera…'
                : st.label === 'NO VIDEO' ? 'Connected, waiting for video' : 'Offline'}
          </b>
          {starting && cam.status !== 'off' && <span>This can take up to half a minute</span>}
          {cam.status === 'off' && onPower && (
            <button type="button" className="btn btn-sm btn-primary cam-start"
              onClick={(e) => { e.stopPropagation(); onPower(true) }}>
              <PowerIcon /> Start camera
            </button>
          )}
        </div>
      )}
      <div className="cam-top">
        <span className={`cam-badge ${st.tone}`}>
          <span className="dot" />{st.label}
        </span>
        {showVideo && cam.dvr && <span className="cam-badge rec"><span className="dot" />REC</span>}
        <span className="spacer" />
        {showVideo && cam.fps != null && <span className="cam-chip">{cam.fps} FPS</span>}
        {cam.threat_score > 0 && <span className={`cam-chip ${cam.threat_score >= 40 ? 'danger' : 'warn'}`}>THREAT {cam.threat_score}</span>}
      </div>
      {showVideo && cam.flags.length > 0 && (
        <div className="cam-flags" role="status">
          {cam.flags.map((f) => (
            <span key={`${f.type}:${f.label}`} className="cam-flag">
              <span className="dot" />
              <b>{FLAG[f.type] || 'ALERT'}</b>
              {f.label && f.type !== 'WEAPON_DETECTED' && <span>{f.label}</span>}
              {f.origin && <span className="cam-flag-from">from {f.origin}</span>}
            </span>
          ))}
        </div>
      )}
      <div className="cam-bottom">
        <div className="cam-name">{cam.name}</div>
        {cam.location && cam.location !== cam.name && <div className="cam-loc">{cam.location}</div>}
      </div>
    </>
  )
}

export function CamFullscreen({ cam, alerting, onClose }) {
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  return (
    <div className="cam-fullscreen-overlay" role="dialog" aria-modal="true" aria-label={`Live feed — ${cam.name}`}>
      <div className="cam-fullscreen-bar">
        <div className="cam-fullscreen-title">
          {cam.name}
          {alerting && <Tag tone="danger">THREAT</Tag>}
        </div>
        <button type="button" className="icon-btn cam-fullscreen-close" onClick={onClose} aria-label="Close full-screen view">
          <Icons.close />
        </button>
      </div>
      <div className={`cam-tile cam-fullscreen-tile ${cam.status} ${alerting ? 'alerting' : ''}`}>
        <CamFeed cam={cam} objectFit="contain" />
      </div>
    </div>
  )
}

function PtzPad({ cameraId }) {
  const [state, setState] = useState(null)
  const [presetName, setPresetName] = useState('Gate')
  const { push: toast } = useToast()
  const moving = useRef(false)

  // Run a PTZ command and show its result; a failure is reported instead of being dropped.
  const run = async (call, failText) => {
    try {
      setState(await call())
    } catch (e) {
      toast(`${failText}: ${e.message || 'request failed'}`, 'danger')
    }
  }

  useEffect(() => {
    if (!cameraId) return
    fetchPtz(cameraId).then(setState).catch(() => {})
  }, [cameraId])

  const move = (pan, tilt, zoom = 0) => {
    moving.current = true
    return run(() => ptzMove(cameraId, { pan, tilt, zoom }), 'Could not move the camera')
  }
  // Pointer-leave also fires when nothing is held, so only send a stop after a move.
  const stop = async () => {
    if (!moving.current) return
    moving.current = false
    try { setState(await ptzStop(cameraId)) } catch { /* the next move reports the problem */ }
  }

  if (!cameraId) return <Empty icon={Icons.camera}>Select a camera to control it</Empty>

  const mode = state?.mode || 'digital'
  const dig = state?.digital || { pan: 0, tilt: 0, zoom: 1 }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <Seg
          value={mode}
          onChange={(m) => run(() => ptzSetMode(cameraId, m), 'Could not switch mode')}
          options={[{ value: 'digital', label: 'Digital' }, { value: 'onvif', label: 'Camera motor' }]}
        />
        <Tag tone={state?.onvif?.configured ? 'ok' : 'muted'}>
          {state?.onvif?.configured ? `ONVIF ${state.onvif.host}` : 'No motorised camera set up'}
        </Tag>
      </div>

      <div className="ptz-pad">
        <button type="button" className="ptz-btn" onPointerDown={() => move(0, 1)} onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop} aria-label="Tilt up"><Chevron dir="up" /></button>
        <div className="ptz-mid">
          <button type="button" className="ptz-btn" onPointerDown={() => move(-1, 0)} onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop} aria-label="Pan left"><Chevron dir="left" /></button>
          <button type="button" className="ptz-btn ptz-home" onClick={() => run(() => ptzHome(cameraId), 'Could not return to the home position')} aria-label="Return to home position" title="Home position"><HomeIcon /></button>
          <button type="button" className="ptz-btn" onPointerDown={() => move(1, 0)} onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop} aria-label="Pan right"><Chevron dir="right" /></button>
        </div>
        <button type="button" className="ptz-btn" onPointerDown={() => move(0, -1)} onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop} aria-label="Tilt down"><Chevron dir="down" /></button>
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
        <span className="muted" style={{ fontSize: '0.75rem' }}>Zoom</span>
        <button type="button" className="btn btn-sm" onPointerDown={() => move(0, 0, -0.5)} onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop} aria-label="Zoom out">−</button>
        <progress max="7" value={Number(dig.zoom) - 1} style={{ flex: 1 }} aria-label="Zoom level" />
        <button type="button" className="btn btn-sm" onPointerDown={() => move(0, 0, 0.5)} onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop} aria-label="Zoom in">+</button>
        <b style={{ fontSize: '0.8rem', width: 36 }}>{Number(dig.zoom).toFixed(1)}×</b>
      </div>

      <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
        <input className="input" style={{ width: 100, padding: '4px 8px' }} value={presetName} maxLength={30} aria-label="Preset name" onChange={(e) => setPresetName(e.target.value)} />
        <button type="button" className="btn btn-sm" onClick={() => run(() => ptzSavePreset(cameraId, presetName.trim() || 'Preset'), 'Could not save the preset')}>Save position</button>
        {(state?.presets || []).map((p) => (
          <button type="button" key={p} className="btn btn-sm btn-primary" title={`Go to ${p}`} onClick={() => run(() => ptzGotoPreset(cameraId, p), `Could not go to ${p}`)}>{p}</button>
        ))}
      </div>
      {state?.last_error && <p className="muted" style={{ fontSize: '0.72rem', marginTop: 8, color: 'var(--warn)' }}>Camera motor: {state.last_error}. Commands are being simulated.</p>}
      <p className="muted" style={{ fontSize: '0.72rem', marginTop: 8 }}>
        Digital zooms and pans inside the picture. Camera motor moves a motorised (ONVIF) camera. Hold a button to keep moving.
      </p>
    </div>
  )
}

// Video wall layouts. All fits every camera; 1 shows the selected (or alerting) camera large.
const WALL_LAYOUTS = [
  { value: 'auto', label: 'All' },
  { value: '1', label: '1' },
  { value: '4', label: '2×2' },
  { value: '9', label: '3×3' },
]

const TOUR_SECONDS = 10

function readWallLayout() {
  try { return localStorage.getItem('aegis_wall') || 'auto' } catch { return 'auto' }
}

export function LiveMonitoring({ ctx }) {
  const { systemStatus, cameras, threatLevel, streamingCams = [], me, captureEvent, liveFocus, power = {}, setPower } = ctx
  const [selectedId, setSelectedId] = useState(liveFocus?.cameraId || null)
  // A camera picked in the cameras panel while this page is already open.
  const [seenFocus, setSeenFocus] = useState(liveFocus || null)
  if (liveFocus !== seenFocus) {
    setSeenFocus(liveFocus)
    if (liveFocus?.cameraId) setSelectedId(liveFocus.cameraId)
  }
  const [fullscreenId, setFullscreenId] = useState(null)
  const [timeline, setTimeline] = useState([])
  const [coverageHrs, setCoverageHrs] = useState(0)
  const [scrub, setScrub] = useState(100)
  const [replayUrl, setReplayUrl] = useState(null)
  const [replayBusy, setReplayBusy] = useState(false)
  const [replayError, setReplayError] = useState('')
  const replayRef = useRef(null)
  useEffect(() => () => { if (replayRef.current) URL.revokeObjectURL(replayRef.current) }, [])

  // Cameras stay off until someone starts them here; `power` says which ones are switched on.
  const { push: toast } = useToast()
  const [ask, confirmDialog] = useConfirm()
  const [starting, setStarting] = useState(() => new Set())
  const canPower = can(me?.role, 'camera.power')

  const switchCamera = async (cam, on) => {
    if (!on && !(await ask({ title: 'Pause camera', message: `Pause "${cam.name}"? Detection and recording on it stop until it is started again.`, confirmLabel: 'Pause', danger: true }))) return
    try {
      setPower(await setCameraPower(cam.camera_id, on))
      setStarting((prev) => { const next = new Set(prev); if (on) next.add(cam.camera_id); else next.delete(cam.camera_id); return next })
      if (on) setTimeout(() => setStarting((prev) => { const next = new Set(prev); next.delete(cam.camera_id); return next }), 45000)
    } catch (e) {
      toast(`Could not ${on ? 'start' : 'stop'} the camera: ${e.message || 'request failed'}`, 'danger')
    }
  }

  // One list: registered cameras, overlaid with live heartbeat + stream state.
  const camList = useMemo(() => buildCamList(cameras, systemStatus, streamingCams, power, ctx.unplugged),
    [cameras, systemStatus, streamingCams, power, ctx.unplugged])

  const counts = {
    live: camList.filter((c) => c.status === 'live').length,
    online: camList.filter((c) => c.status === 'live' || c.status === 'online').length,
  }

  const activeCam = camList.find((c) => c.camera_id === selectedId)?.camera_id || camList[0]?.camera_id
  const activeInfo = camList.find((c) => c.camera_id === activeCam)
  const alertingId = threatLevel === 'critical' ? camList.find((c) => c.threat_score >= 40)?.camera_id : null
  const fullscreenCam = camList.find((c) => c.camera_id === fullscreenId)

  const [layout, setLayoutState] = useState(readWallLayout)
  const setLayout = (v) => {
    setLayoutState(v)
    try { localStorage.setItem('aegis_wall', v) } catch { /* ignore */ }
  }
  // Camera tour: with more cameras than tiles, step through them every TOUR_SECONDS.
  const [tour, setTourState] = useState(() => { try { return localStorage.getItem('aegis_tour') === '1' } catch { return false } })
  const setTour = (on) => {
    setTourState(on)
    try { localStorage.setItem('aegis_tour', on ? '1' : '0') } catch { /* ignore */ }
  }
  const [tourStep, setTourStep] = useState(0)
  const slots = layout === 'auto' ? camList.length : Number(layout)
  const pages = Math.max(1, Math.ceil(camList.length / Math.max(1, slots)))
  const touring = tour && layout !== 'auto' && pages > 1
  useEffect(() => {
    if (!touring) return undefined
    const t = setInterval(() => setTourStep((n) => n + 1), TOUR_SECONDS * 1000)
    return () => clearInterval(t)
  }, [touring])
  const pageNo = touring ? tourStep % pages : 0

  // The camera with a threat in view is always on the wall, whatever the layout or tour page.
  const alerting = camList.find((c) => c.camera_id === alertingId)
  let wall
  if (layout === '1') {
    wall = [alerting || (touring ? camList[pageNo] : camList.find((c) => c.camera_id === activeCam))].filter(Boolean)
  } else {
    wall = camList.slice(pageNo * slots, pageNo * slots + slots)
    if (alerting && !wall.includes(alerting)) wall = [alerting, ...wall.slice(0, slots - 1)]
  }
  const n = layout === 'auto' ? wall.length : slots
  const cols = n <= 1 ? 1 : n <= 4 ? 2 : n <= 9 ? 3 : 4

  const loadTimeline = useCallback(() => {
    if (!activeCam) return
    fetchVmsTimeline({ cameraId: activeCam, hours: 24 }).then((r) => {
      setTimeline(r.segments || [])
      setCoverageHrs(r.continuous_coverage_hours || 0)
    }).catch(() => {})
  }, [activeCam])
  useEffect(() => { loadTimeline() }, [loadTimeline, streamingCams.length])

  const scrubToReplay = async () => {
    if (!activeCam || !timeline.length) return
    setReplayBusy(true)
    setReplayError('')
    try {
      const idx = Math.min(timeline.length - 1, Math.floor((scrub / 100) * timeline.length))
      const t = timeline[idx]?.start || new Date().toISOString()
      const { blobUrl } = await openVmsPlayback(activeCam, t)
      if (replayRef.current) URL.revokeObjectURL(replayRef.current)
      replayRef.current = blobUrl
      setReplayUrl(blobUrl)
    } catch (e) {
      setReplayError(e.message || 'No recording at this time')
    } finally {
      setReplayBusy(false)
    }
  }

  // `online` stays true after the first heartbeat; a camera reporting now is what "on" means.
  const detecting = Object.keys(systemStatus?.cameras || {}).length > 0
  const pipelineLabel = detecting ? 'Detection on' : 'Detection off'

  return (
    <>
      <div className="wall-bar">
        <span className="wall-summary">
          <b>{counts.live}</b> of {camList.length} camera{camList.length === 1 ? '' : 's'} live
          {!detecting && camList.length > 0 && <span className="muted"> · detection is off</span>}
        </span>
        <span className="spacer" />
        {layout !== 'auto' && pages > 1 && (
          <button type="button" className={`btn btn-sm ${tour ? 'btn-primary' : ''}`} aria-pressed={tour}
            title={`Show every camera in turn, ${TOUR_SECONDS} s each page`} onClick={() => setTour(!tour)}>
            {tour ? `Tour · page ${pageNo + 1} of ${pages}` : 'Tour cameras'}
          </button>
        )}
        <Seg value={layout} onChange={setLayout} options={WALL_LAYOUTS} />
      </div>

      {camList.length === 0 ? (
        <Card><Empty icon={Icons.camera}>No cameras yet. Add one under Set up → Cameras.</Empty></Card>
      ) : (
        <div className="cam-grid wall" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {wall.map((c) => (
            <div key={c.camera_id} role="button" tabIndex={0}
              className={`cam-tile ${c.status} ${c.camera_id === activeCam ? 'selected' : ''} ${c.camera_id === alertingId ? 'alerting' : ''}`}
              aria-label={`${c.name}: select (double-click for full screen)`}
              onClick={() => setSelectedId(c.camera_id)}
              onDoubleClick={() => setFullscreenId(c.camera_id)}
              onKeyDown={(e) => { if (e.key === 'Enter') setFullscreenId(c.camera_id) }}>
              <CamFeed cam={c} starting={starting.has(c.camera_id) && c.status !== 'live'}
                onPower={canPower && c.camera_id in power ? (on) => switchCamera(c, on) : undefined} />
              <button type="button" className="cam-expand" title="Full screen" aria-label={`${c.name} full screen`}
                onClick={(e) => { e.stopPropagation(); setFullscreenId(c.camera_id) }}>
                <ExpandIcon />
              </button>
              <button type="button" className={`cam-expand cam-pin ${ctx.pinned === c.camera_id ? 'on' : ''}`}
                title={ctx.pinned === c.camera_id ? 'Unpin' : 'Keep this camera in view on other pages'}
                aria-label={ctx.pinned === c.camera_id ? `Unpin ${c.name}` : `Pin ${c.name}`} aria-pressed={ctx.pinned === c.camera_id}
                onClick={(e) => { e.stopPropagation(); ctx.pinCamera?.(ctx.pinned === c.camera_id ? null : c.camera_id) }}>
                <PinIcon />
              </button>
              {canPower && c.camera_id in power && c.status !== 'off' && (
                <button type="button" className="cam-expand cam-stop" title="Pause camera" aria-label={`Pause ${c.name}`}
                  onClick={(e) => { e.stopPropagation(); switchCamera(c, false) }}>
                  <PowerIcon />
                </button>
              )}
            </div>
          ))}
          {Array.from({ length: Math.max(0, n - wall.length) }, (_, i) => (
            <div key={`empty-${i}`} className="cam-tile empty">No camera</div>
          ))}
        </div>
      )}

      <div className="live-layout">
        <div className="live-main">
          {layout !== 'auto' && (
          <Card title="Cameras" sub={activeInfo ? `Selected: ${activeInfo.name}` : `${camList.length}`} flush
            actions={<Pill tone={detecting ? 'ok' : 'warn'}>{pipelineLabel}</Pill>}>
            <div className="cam-list">
              {camList.map((c) => {
                const isStarting = starting.has(c.camera_id) && c.status !== 'live'
                return (
                  <div key={c.camera_id} className="side-cam">
                    <button type="button" className={`cam-row ${c.camera_id === activeCam ? 'active' : ''}`}
                      onClick={() => setSelectedId(c.camera_id)}>
                      <span className={`status-dot ${STATUS[c.status].tone}`} />
                      <span className="cam-row-main">
                        <b>{c.name}</b>
                        <span>{isStarting ? 'Starting… this can take up to half a minute' : c.location || c.camera_id}</span>
                      </span>
                      <Tag tone={STATUS[c.status].tone}>{STATUS[c.status].label}</Tag>
                    </button>
                    {canPower && c.camera_id in power && (
                      c.status === 'off'
                        ? <button type="button" className="btn btn-sm btn-primary" onClick={() => switchCamera(c, true)}><PowerIcon /> Start</button>
                        : <button type="button" className="icon-btn" title="Pause camera" aria-label={`Pause ${c.name}`} onClick={() => switchCamera(c, false)}><PowerIcon /></button>
                    )}
                    <button type="button" className="icon-btn" title="Full screen" aria-label={`${c.name} full screen`} onClick={() => setFullscreenId(c.camera_id)}>
                      <ExpandIcon />
                    </button>
                  </div>
                )
              })}
              {camList.length === 0 && <Empty icon={Icons.camera}>No cameras yet. Add one under Cameras.</Empty>}
            </div>
            {!detecting && camList.length > 0 && (
              <p className="live-hint" style={{ padding: '0 14px 14px' }}>The analysis pipeline is not reporting. Cameras stay offline until it is running.</p>
            )}
          </Card>
          )}

      <Card title="Recordings" sub={`${timeline.length} clips · ${coverageHrs.toFixed(1)} h recorded in 24 hours · ${activeInfo?.name || 'no camera selected'}`}
        actions={<button className="btn btn-sm" onClick={loadTimeline}>Refresh</button>}>
        {timeline.length === 0 ? (
          <Empty icon={Icons.clock}>No recordings for this camera yet. Segments are saved every 60 seconds while video is flowing.</Empty>
        ) : (
          <>
            <div className="vms-rail">
              {timeline.map((s) => (
                <div key={s.id} className={`vms-seg ${s.trigger === 'event' ? 'event' : 'cont'}`}
                  title={`${s.trigger} · ${s.start}`} style={{ flex: Math.max(0.5, s.duration || 1) }} />
              ))}
            </div>
            <div className="vms-legend">
              <span><i className="cont" />Continuous</span><span><i className="event" />Alert event</span>
            </div>
            <div className="vms-controls">
              <input type="range" min="0" max="100" value={scrub} aria-label="Scrub position"
                onChange={(e) => setScrub(Number(e.target.value))} />
              <button className="btn btn-primary" disabled={replayBusy} onClick={scrubToReplay}>
                <Icons.eye /> {replayBusy ? 'Loading…' : 'Play'}
              </button>
            </div>
            {replayError && <div className="login-error" role="alert" style={{ marginTop: 10 }}>{replayError}</div>}
            {replayUrl && <video src={replayUrl} controls autoPlay className="vms-player" />}
            <div className="vms-list">
              {timeline.slice().reverse().slice(0, 6).map((s) => (
                <div key={s.id} className="row">
                  <div>
                    <b>{s.alert_type || (s.trigger === 'event' ? 'Event' : 'Continuous recording')}</b>
                    <div className="meta">{timeAgo(s.start)} · {Math.round(s.duration || 0)}s</div>
                  </div>
                  <Tag tone={s.trigger === 'event' ? 'danger' : 'ok'}>{s.trigger}</Tag>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>
        </div>

        <div className="live-rail">
          {me?.role && me.role !== 'viewer' && <CaptureBasket captureEvent={captureEvent} />}
          {can(me?.role, 'ptz') && (
            <Card title="Pan, tilt and zoom" sub={activeInfo?.name || 'No camera selected'}>
              <PtzPad cameraId={activeCam} />
            </Card>
          )}
        </div>
      </div>

      {confirmDialog}
      {fullscreenCam && (
        <CamFullscreen cam={fullscreenCam} alerting={fullscreenCam.camera_id === alertingId}
          onClose={() => setFullscreenId(null)} />
      )}
    </>
  )
}
