/* One status chip for the top bar. Its colour is the worst problem; opening it says what
   is wrong and what to do, instead of three pills that only say "off". */
import { timeAgo } from './ui'

const MODEL_LABEL = {
  human_detector: 'Person detection',
  weapon_detector: 'Weapon detection',
  vehicle_detector: 'Vehicle detection',
  pose_analyzer: 'Pose / fall checks',
  fire_detector: 'Fire & smoke detection',
}
const MODEL_STATE = {
  ok: ['ok', 'Ready'],
  missing: ['danger', 'Model file missing: this check is off'],
  not_installed: ['muted', 'Optional, not installed'],
  disabled: ['muted', 'Turned off in config.yaml'],
}
const SLA = { ok: ['ok', 'Reporting'], degraded: ['warn', 'Slow to report'] }
const AI_STUCK_S = 15     // no finished AI pass for this long: video still flows, detection does not

/** What is wrong, worst first: [{tone, text}] */
function systemProblems({ connected, status, camList }) {
  const out = []
  if (!connected) out.push({ tone: 'danger', text: 'Lost the live connection to the server. Retrying; alerts may arrive late.' })
  if (status) {
    const reporting = Object.keys(status.cameras || {}).length
    if (!reporting) {
      out.push({
        tone: 'warn',
        text: camList.length
          ? 'No camera is sending detections. Start the detection pipeline (./run.sh, or python main.py --multi) and check the cameras are switched on.'
          : 'No cameras are set up yet. Add one on the Cameras page.',
      })
    }
    const stuck = Object.entries(status.cameras || {}).filter(([, c]) => c.ai_age_s > AI_STUCK_S)
    if (stuck.length) {
      const names = stuck.map(([id]) => camList.find((c) => c.camera_id === id)?.name || id)
      out.push({
        tone: 'danger',
        text: `Detection is stuck on ${names.join(', ')}: video still plays but nothing is analysed. The pipeline restarts itself after 2 minutes; if not, restart it.`,
      })
    }
    const slow = Object.values(status.cameras || {}).filter((c) => c.sla === 'degraded').length
    if (slow) out.push({ tone: 'warn', text: `${slow} camera${slow === 1 ? ' is' : 's are'} slow to report: the computer may be overloaded.` })
    if (status.offline_cameras) {
      out.push({ tone: 'warn', text: `${status.offline_cameras} camera${status.offline_cameras === 1 ? '' : 's'} stopped reporting (paused, unplugged or crashed).` })
    }
    const missing = Object.entries(status.models || {}).filter(([, v]) => v === 'missing').map(([k]) => MODEL_LABEL[k] || k)
    if (missing.length) out.push({ tone: 'warn', text: `${missing.join(', ')} ${missing.length === 1 ? 'is' : 'are'} off: model file missing.` })
  }
  return out
}

export function SystemStatus({ connected, status, camList, open, setOpen }) {
  const problems = systemProblems({ connected, status, camList })
  const tone = problems.some((p) => p.tone === 'danger') ? 'danger' : problems.length ? 'warn' : 'ok'
  const reporting = status ? Object.keys(status.cameras || {}).length : 0
  const label = !connected ? 'Reconnecting…' : !reporting ? 'Detection off' : problems.length ? 'Needs attention' : 'All systems normal'

  return (
    <div className="account sys">
      <button type="button" className={`pill pill-${tone} pill-btn`} aria-haspopup="dialog" aria-expanded={open}
        onClick={() => setOpen(!open)} title="System status">
        <span className="dot" />{label}
      </button>
      {open && (
        <>
          <button type="button" className="menu-scrim" aria-label="Close system status" onClick={() => setOpen(false)} />
          <div className="account-menu sys-panel" role="dialog" aria-label="System status">
            <h3>System status</h3>
            {problems.length === 0 ? (
              <p className="sys-ok">Connected, {reporting} camera{reporting === 1 ? '' : 's'} reporting, all detection models ready.</p>
            ) : (
              <ul className="sys-problems">
                {problems.map((p) => <li key={p.text} className={`tone-${p.tone}`}>{p.text}</li>)}
              </ul>
            )}

            {camList.length > 0 && (
              <>
                <div className="sys-sub">Cameras</div>
                <dl className="sys-rows">
                  {camList.map((c) => {
                    const beat = status?.cameras?.[c.camera_id]
                    const [t, text] = beat ? (SLA[beat.sla] || SLA.ok) : ['muted', c.status === 'off' ? 'Paused' : 'Offline']
                    return (
                      <div key={c.camera_id}>
                        <dt>{c.name}</dt>
                        <dd>
                          <span className={`tone-${t}`}>{text}</span>
                          {beat?.fps != null && <span className="mono"> · {Math.round(beat.fps)} fps</span>}
                          {beat?.infer_ms != null && (
                            <span className={`mono ${beat.ai_age_s > AI_STUCK_S ? 'tone-danger' : ''}`} title="Time of the last AI pass on this camera">
                              {' · '}{beat.ai_age_s > AI_STUCK_S ? `AI stuck ${Math.round(beat.ai_age_s)} s` : `AI ${beat.infer_ms} ms`}
                            </span>
                          )}
                          {beat?.last_seen && <span> · {timeAgo(beat.last_seen)}</span>}
                        </dd>
                      </div>
                    )
                  })}
                </dl>
              </>
            )}

            {status?.models && Object.keys(status.models).length > 0 && (
              <>
                <div className="sys-sub">Detection models</div>
                <dl className="sys-rows">
                  {Object.entries(status.models).map(([k, v]) => {
                    const [t, text] = MODEL_STATE[v] || ['muted', v]
                    return (
                      <div key={k}><dt>{MODEL_LABEL[k] || k}</dt><dd className={`tone-${t}`}>{text}</dd></div>
                    )
                  })}
                </dl>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
