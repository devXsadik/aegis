import { useEffect, useMemo, useState } from 'react'
import { Card, Icons, Seg, Pill, Tag, Empty, timeAgo } from '../components/ui'
import {
  liveStreamUrl,
  fetchVmsTimeline, fetchPtz, ptzMove, ptzStop, ptzHome, ptzSetMode,
  ptzSavePreset, ptzGotoPreset, openVmsPlayback,
} from '../services/api'

function seeded(i) {
  const x = Math.sin(i * 999 + 7) * 10000
  return x - Math.floor(x)
}

function useCamFeed(cam, index, aiOverlay, alerting) {
  const online = cam?.online ?? true
  const fps = cam?.fps ?? Math.round(22 + seeded(index) * 8)
  const [streamFailed, setStreamFailed] = useState(false)
  const streaming = cam?.streaming && !streamFailed

  const boxes = useMemo(() => {
    if (!aiOverlay || !online || streaming) return []
    const n = 1 + Math.floor(seeded(index * 3) * 2)
    return Array.from({ length: n }, (_, k) => {
      const threat = alerting && k === 0
      return {
        left: 12 + seeded(index * 7 + k) * 55,
        top: 18 + seeded(index * 11 + k) * 40,
        w: 14 + seeded(index * 13 + k) * 12,
        h: 26 + seeded(index * 17 + k) * 18,
        label: threat ? `THREAT ${(88 + seeded(index + k) * 10).toFixed(0)}%` : `person ${(72 + seeded(index * 5 + k) * 25).toFixed(0)}%`,
        threat,
      }
    })
  }, [aiOverlay, online, index, alerting, streaming])

  const label = cam?.name || cam?.camera_location || `CAM-${String(index + 1).padStart(2, '0')}`

  return { online, fps, streaming, boxes, label, setStreamFailed }
}

function CamFeed({ cam, index, aiOverlay, alerting, objectFit = 'cover' }) {
  const { online, fps, streaming, boxes, label, setStreamFailed } = useCamFeed(cam, index, aiOverlay, alerting)

  return (
    <>
      {streaming && (
        <img
          src={liveStreamUrl(cam.camera_id)}
          alt={label}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit }}
          onError={() => setStreamFailed(true)}
        />
      )}
      <div className="scanline" />
      <div className="cam-label">
        <span className="rec-dot" />
        {label}
        {streaming && <span style={{ color: 'var(--ok)' }}>· LIVE</span>}
        {cam?.dvr && <span style={{ color: 'var(--danger)' }}>· REC</span>}
      </div>
      {online ? (
        <>
          {!streaming && boxes.map((b, k) => (
            <div key={k} className={`bbox ${b.threat ? 'threat' : ''}`} style={{ left: `${b.left}%`, top: `${b.top}%`, width: `${b.w}%`, height: `${b.h}%` }}>
              <span className="bbox-tag">{b.label}</span>
            </div>
          ))}
          <div className="cam-stats">
            <span>{fps} FPS{streaming ? ' · MJPEG' : ''}</span>
            <span>THREAT {cam?.threat_score ?? 0}</span>
          </div>
        </>
      ) : (
        <div className="cam-offline"><Icons.camera /><div>Signal lost</div></div>
      )}
    </>
  )
}

function CamTile({ cam, index, aiOverlay, alerting, focused, onFocus }) {
  return (
    <div
      className={`cam-tile ${alerting ? 'alerting' : ''}`}
      onClick={onFocus}
      style={{ cursor: 'pointer', outline: focused ? '2px solid var(--primary)' : 'none' }}
      title="Click for full-screen view"
    >
      <CamFeed cam={cam} index={index} aiOverlay={aiOverlay} alerting={alerting} />
    </div>
  )
}

function CamFullscreen({ cam, index, aiOverlay, alerting, onClose }) {
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

  const label = cam?.name || cam?.camera_location || `CAM-${String(index + 1).padStart(2, '0')}`

  return (
    <div className="cam-fullscreen-overlay" role="dialog" aria-modal="true" aria-label={`Live feed — ${label}`}>
      <div className="cam-fullscreen-bar">
        <div className="cam-fullscreen-title">
          <span className="rec-dot" />
          {label}
          {alerting && <Tag tone="danger">THREAT</Tag>}
        </div>
        <button type="button" className="icon-btn cam-fullscreen-close" onClick={onClose} aria-label="Close full-screen view">
          <Icons.close />
        </button>
      </div>
      <div className={`cam-tile cam-fullscreen-tile ${alerting ? 'alerting' : ''}`}>
        <CamFeed cam={cam} index={index} aiOverlay={aiOverlay} alerting={alerting} objectFit="contain" />
      </div>
    </div>
  )
}

function PtzPad({ cameraId }) {
  const [state, setState] = useState(null)
  const [presetName, setPresetName] = useState('Gate')

  useEffect(() => {
    if (!cameraId) return
    fetchPtz(cameraId).then(setState).catch(() => {})
  }, [cameraId])

  const move = async (pan, tilt, zoom = 0) => {
    try {
      setState(await ptzMove(cameraId, { pan, tilt, zoom }))
    } catch { /* offline */ }
  }
  const stop = async () => { try { setState(await ptzStop(cameraId)) } catch { /* */ } }

  if (!cameraId) return <Empty icon={Icons.camera}>Select a camera tile</Empty>

  const mode = state?.mode || 'digital'
  const dig = state?.digital || { pan: 0, tilt: 0, zoom: 1 }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <Seg
          value={mode}
          onChange={async (m) => setState(await ptzSetMode(cameraId, m))}
          options={[{ value: 'digital', label: 'Digital PTZ' }, { value: 'onvif', label: 'ONVIF' }]}
        />
        <Tag tone={state?.onvif?.configured ? 'ok' : 'muted'}>
          {state?.onvif?.configured ? `ONVIF ${state.onvif.host}` : 'ONVIF simulator'}
        </Tag>
      </div>

      <div className="ptz-pad">
        <button className="ptz-btn" onMouseDown={() => move(0, 1)} onMouseUp={stop} onMouseLeave={stop}>▲</button>
        <div className="ptz-mid">
          <button className="ptz-btn" onMouseDown={() => move(-1, 0)} onMouseUp={stop} onMouseLeave={stop}>◀</button>
          <button className="ptz-btn ptz-home" onClick={async () => setState(await ptzHome(cameraId))}>⌂</button>
          <button className="ptz-btn" onMouseDown={() => move(1, 0)} onMouseUp={stop} onMouseLeave={stop}>▶</button>
        </div>
        <button className="ptz-btn" onMouseDown={() => move(0, -1)} onMouseUp={stop} onMouseLeave={stop}>▼</button>
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
        <span className="muted" style={{ fontSize: '0.75rem' }}>Zoom</span>
        <button className="btn btn-sm" onMouseDown={() => move(0, 0, -0.5)} onMouseUp={stop}>−</button>
        <input
          type="range" min="1" max="8" step="0.1" value={dig.zoom}
          readOnly
          style={{ flex: 1 }}
        />
        <button className="btn btn-sm" onMouseDown={() => move(0, 0, 0.5)} onMouseUp={stop}>+</button>
        <b style={{ fontSize: '0.8rem', width: 36 }}>{Number(dig.zoom).toFixed(1)}×</b>
      </div>

      <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
        <input className="input" style={{ width: 100, padding: '4px 8px' }} value={presetName} onChange={(e) => setPresetName(e.target.value)} />
        <button className="btn btn-sm" onClick={async () => setState(await ptzSavePreset(cameraId, presetName || 'Preset'))}>Save preset</button>
        {(state?.presets || []).map((p) => (
          <button key={p} className="btn btn-sm btn-primary" onClick={async () => setState(await ptzGotoPreset(cameraId, p))}>{p}</button>
        ))}
      </div>
      {state?.last_error && <p className="muted" style={{ fontSize: '0.72rem', marginTop: 8, color: 'var(--warn)' }}>ONVIF: {state.last_error} (simulator active)</p>}
      <p className="muted" style={{ fontSize: '0.72rem', marginTop: 8 }}>
        Digital PTZ crops the live stream. ONVIF sends SOAP ContinuousMove to the camera (or simulates if unreachable).
      </p>
    </div>
  )
}

export function LiveMonitoring({ ctx }) {
  const { systemStatus, cameras, threatLevel, streamingCams = [] } = ctx
  const [layout, setLayout] = useState(4)
  const [aiOverlay, setAiOverlay] = useState(true)
  const [focused, setFocused] = useState(0)
  const [fullscreenIdx, setFullscreenIdx] = useState(null)
  const [timeline, setTimeline] = useState([])
  const [coverageHrs, setCoverageHrs] = useState(0)
  const [scrub, setScrub] = useState(100)
  const [replayUrl, setReplayUrl] = useState(null)
  const [replayBusy, setReplayBusy] = useState(false)

  const streamingSet = new Set(streamingCams)
  const liveCams = Object.entries(systemStatus?.cameras || {}).map(([id, c]) => ({
    camera_id: id, name: c.camera_location, fps: c.fps, threat_score: c.threat_score,
    online: true, streaming: streamingSet.has(id), dvr: true,
  }))
  const registered = cameras.map((c) => ({
    camera_id: c.camera_id, name: c.name || c.location, online: c.active,
    streaming: streamingSet.has(c.camera_id), dvr: true,
  }))
  const source = liveCams.length ? liveCams : registered
  const tiles = Array.from({ length: layout }, (_, i) => source[i] || null)
  const alertingIdx = threatLevel === 'critical' ? 0 : -1
  const activeCam = tiles[focused]?.camera_id || source[0]?.camera_id

  useEffect(() => {
    fetchVmsTimeline({ cameraId: activeCam, hours: 24 }).then((r) => {
      setTimeline(r.segments || [])
      setCoverageHrs(r.continuous_coverage_hours || 0)
    }).catch(() => {})
  }, [activeCam, streamingCams.length])

  const loadTimeline = () => {
    fetchVmsTimeline({ cameraId: activeCam, hours: 24 }).then((r) => {
      setTimeline(r.segments || [])
      setCoverageHrs(r.continuous_coverage_hours || 0)
    }).catch(() => {})
  }

  const scrubToReplay = async () => {
    if (!activeCam || !timeline.length) return
    setReplayBusy(true)
    try {
      const idx = Math.min(timeline.length - 1, Math.floor((scrub / 100) * timeline.length))
      const seg = timeline[idx]
      const t = seg?.start || new Date().toISOString()
      const { blobUrl } = await openVmsPlayback(activeCam, t)
      if (replayUrl) URL.revokeObjectURL(replayUrl)
      setReplayUrl(blobUrl)
    } catch (e) {
      alert(e.message || 'No recording at this time')
    } finally {
      setReplayBusy(false)
    }
  }

  return (
    <>
      <Card
        title="Live Monitoring Center"
        sub={
          streamingCams.length > 0
            ? `${streamingCams.length} live · DVR coverage ${coverageHrs.toFixed(2)}h (24h window)`
            : systemStatus?.online
              ? 'pipeline online — waiting for video frames · DVR recording when frames arrive'
              : 'pipeline offline — start: python main.py --video data/demo/clips/sample.mp4'
        }
        actions={
          <div className="cam-controls">
            <Seg
              value={layout}
              onChange={setLayout}
              options={[{ value: 1, label: '1' }, { value: 4, label: '4' }, { value: 9, label: '9' }, { value: 16, label: '16' }]}
            />
            <button className={`btn btn-sm ${aiOverlay ? 'btn-primary' : ''}`} onClick={() => setAiOverlay(!aiOverlay)}>
              <Icons.ai /> AI {aiOverlay ? 'ON' : 'OFF'}
            </button>
            <Pill tone={systemStatus?.online ? 'ok' : 'warn'}>{systemStatus?.online ? 'LIVE' : 'STANDBY'}</Pill>
            <Pill tone="danger">DVR</Pill>
          </div>
        }
      >
        <div className={`cam-grid n${layout}`}>
          {tiles.map((cam, i) => (
            <CamTile
              key={i}
              cam={cam}
              index={i}
              aiOverlay={aiOverlay}
              alerting={i === alertingIdx}
              focused={focused === i && layout > 1}
              onFocus={() => {
                setFocused(i)
                setFullscreenIdx(i)
              }}
            />
          ))}
        </div>
      </Card>

      <div className="grid grid-23" style={{ marginTop: 14 }}>
        <Card title="Timeline Scrubber" sub={`${timeline.length} segments · continuous + events`}>
          {timeline.length === 0 ? (
            <Empty icon={Icons.clock}>
              No DVR segments yet. Run the pipeline with <code>DVR_ENABLED=true</code> — segments close every 60s.
            </Empty>
          ) : (
            <>
              <div className="vms-rail">
                {timeline.map((s) => (
                  <div
                    key={s.id}
                    className={`vms-seg ${s.trigger === 'event' ? 'event' : 'cont'}`}
                    title={`${s.trigger} ${s.start}`}
                    style={{ flex: Math.max(0.5, s.duration || 1) }}
                  />
                ))}
              </div>
              <label className="field" style={{ marginTop: 12 }}>
                Scrub position
                <input type="range" min="0" max="100" value={scrub} onChange={(e) => setScrub(Number(e.target.value))} />
              </label>
              <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                <button className="btn btn-primary" disabled={replayBusy} onClick={scrubToReplay}>
                  <Icons.eye /> {replayBusy ? 'Loading…' : 'Play at scrub'}
                </button>
                <button className="btn btn-sm" onClick={loadTimeline}>Refresh</button>
                <span className="muted" style={{ fontSize: '0.75rem', alignSelf: 'center' }}>
                  Camera: <b>{activeCam || '—'}</b>
                </span>
              </div>
              {replayUrl && (
                <video src={replayUrl} controls autoPlay style={{ width: '100%', marginTop: 12, borderRadius: 8, background: '#000' }} />
              )}
              <div style={{ marginTop: 12, maxHeight: 160, overflowY: 'auto' }}>
                {timeline.slice().reverse().slice(0, 8).map((s) => (
                  <div key={s.id} className="row">
                    <div>
                      <b>{s.trigger}</b>{s.alert_type ? ` · ${s.alert_type}` : ''}
                      <div className="meta">{timeAgo(s.start)} · {(s.duration || 0).toFixed?.(0) || s.duration}s</div>
                    </div>
                    <Tag tone={s.trigger === 'event' ? 'danger' : 'ok'}>{s.trigger}</Tag>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>

        <Card title="PTZ Control" sub={tiles[focused]?.name || activeCam || '—'}>
          <PtzPad cameraId={activeCam} />
        </Card>
      </div>

      {fullscreenIdx != null && tiles[fullscreenIdx] && (
        <CamFullscreen
          cam={tiles[fullscreenIdx]}
          index={fullscreenIdx}
          aiOverlay={aiOverlay}
          alerting={fullscreenIdx === alertingIdx}
          onClose={() => setFullscreenIdx(null)}
        />
      )}
    </>
  )
}
