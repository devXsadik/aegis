import { useEffect, useMemo, useState } from 'react'
import { Card, Icons, Seg, Pill, Tag, Empty, timeAgo } from '../components/ui'
import { liveStreamUrl, fetchTimeline, recordingFileUrl, getToken } from '../services/api'

/* Deterministic pseudo-random per tile so bounding boxes don't jump every render */
function seeded(i) {
  const x = Math.sin(i * 999 + 7) * 10000
  return x - Math.floor(x)
}

function CamTile({ cam, index, aiOverlay, alerting, focused, onFocus }) {
  const online = cam?.online ?? true
  const fps = cam?.fps ?? Math.round(22 + seeded(index) * 8)
  const [streamFailed, setStreamFailed] = useState(false)
  const streaming = cam?.streaming && !streamFailed
  const boxes = useMemo(() => {
    if (!aiOverlay || !online) return []
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
  }, [aiOverlay, online, index, alerting])

  return (
    <div className={`cam-tile ${alerting ? 'alerting' : ''}`} onClick={onFocus} style={{ cursor: 'pointer', outline: focused ? '2px solid var(--primary)' : 'none' }}>
      {streaming && (
        <img
          src={liveStreamUrl(cam.camera_id)}
          alt={cam?.name || cam.camera_id}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
          onError={() => setStreamFailed(true)}
        />
      )}
      <div className="scanline" />
      <div className="cam-label">
        <span className="rec-dot" />
        {cam?.name || cam?.camera_location || `CAM-${String(index + 1).padStart(2, '0')}`}
        {streaming && <span style={{ color: 'var(--ok)' }}>· LIVE</span>}
      </div>
      {online ? (
        <>
          {!streaming && boxes.map((b, k) => (
            <div key={k} className={`bbox ${b.threat ? 'threat' : ''}`} style={{ left: `${b.left}%`, top: `${b.top}%`, width: `${b.w}%`, height: `${b.h}%` }}>
              <span className="bbox-tag">{b.label}</span>
            </div>
          ))}
          <div className="cam-stats">
            <span>{fps} FPS{streaming ? ' · MJPEG' : ' · 1080p'}</span>
            <span>THREAT {cam?.threat_score ?? 0}</span>
          </div>
        </>
      ) : (
        <div className="cam-offline">
          <Icons.camera />
          <div>Signal lost</div>
        </div>
      )}
    </div>
  )
}

export function LiveMonitoring({ ctx }) {
  const { systemStatus, cameras, threatLevel, streamingCams = [] } = ctx
  const [layout, setLayout] = useState(4)
  const [aiOverlay, setAiOverlay] = useState(true)
  const [focused, setFocused] = useState(0)

  const streamingSet = new Set(streamingCams)
  const liveCams = Object.entries(systemStatus?.cameras || {}).map(([id, c]) => ({
    camera_id: id, name: c.camera_location, fps: c.fps, threat_score: c.threat_score,
    online: true, streaming: streamingSet.has(id),
  }))
  const registered = cameras.map((c) => ({
    camera_id: c.camera_id, name: c.name || c.location, online: c.active,
    streaming: streamingSet.has(c.camera_id),
  }))
  const source = liveCams.length ? liveCams : registered
  const tiles = Array.from({ length: layout }, (_, i) => source[i] || null)
  const alertingIdx = threatLevel === 'critical' ? 0 : -1
  const [timeline, setTimeline] = useState([])

  useEffect(() => {
    fetchTimeline({ hours: 24 }).then((r) => setTimeline(r.events || [])).catch(() => {})
  }, [streamingCams.length])

  return (
    <>
    <Card
      title="Live Monitoring Center"
      sub={
        streamingCams.length > 0
          ? `${streamingCams.length} camera(s) streaming live AI video`
          : systemStatus?.online ? 'pipeline online — waiting for video frames' : 'pipeline offline — tiles show placeholder telemetry'
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
            onFocus={() => setFocused(i)}
          />
        ))}
      </div>
      <div className="toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
        <span className="muted" style={{ fontSize: '0.78rem' }}>Selected: <b>{tiles[focused]?.name || `Tile ${focused + 1}`}</b></span>
        <span className="spacer" />
        <Tag tone="muted">PTZ / audio require camera SDK — clips auto-saved on threat</Tag>
      </div>
    </Card>

    <Card title="Timeline Replay" sub="event-triggered clips · last 24h" style={{ marginTop: 14 }}>
      {timeline.length === 0 && <Empty icon={Icons.clock}>No recordings yet — clips save when threat_score ≥ 40</Empty>}
      {timeline.slice().reverse().slice(0, 12).map((ev) => (
        <div key={ev.id} className="row">
          <div>
            <b>{ev.alert_type || ev.trigger}</b>
            <div className="meta">{ev.camera_id} · {timeAgo(ev.t)}</div>
          </div>
          <a
            className="btn btn-sm"
            href={`${recordingFileUrl(ev.id)}${getToken() ? '' : ''}`}
            target="_blank"
            rel="noreferrer"
            onClick={async (e) => {
              e.preventDefault()
              const token = getToken()
              const res = await fetch(recordingFileUrl(ev.id), {
                headers: token ? { Authorization: `Bearer ${token}` } : {},
              })
              if (!res.ok) return
              const blob = await res.blob()
              window.open(URL.createObjectURL(blob), '_blank')
            }}
          >
            <Icons.eye /> Replay
          </a>
        </div>
      ))}
    </Card>
    </>
  )
}
