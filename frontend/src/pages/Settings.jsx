import { useEffect, useState } from 'react'
import { isAlertSoundMuted, setAlertSoundMuted } from '../hooks/alertNotifications'
import { Card, Icons, Seg, timeAgo, useConfirm } from '../components/ui'
import {
  Badge, DsIcons, EmptyState, ErrorState, SaveBar, SectionHeader, SettingRow, Skeleton,
} from '../components/ds'
import { TwoFactor } from '../components/TwoFactor'
import {
  fetchIntegrationStatus, testIntegration, fetchConfigThresholds, saveConfigThreshold, fetchThresholdSpecs,
  fetchBackups, runBackupNow,
} from '../services/api'
import { useToast } from '../components/Toast'
import { useI18n } from '../hooks/useI18n'
import { LANGS } from '../lib/i18n'
import { canViewPage } from '../lib/permissions'

const SECTION_KEY = 'aegis.settings.section'

/* Order = side-nav order. `phase` marks sections whose full editor arrives later in the roadmap.
   `all` sections are personal and open to every role; the rest are for command roles. The server
   enforces every rule again: this only keeps buttons that would fail off the screen. */
const COMMAND = new Set(['admin', 'supervisor'])
const SECTIONS = [
  { id: 'profile', icon: DsIcons.user, all: true },
  { id: 'notifications', icon: Icons.bell, all: true },
  { id: 'cameras', icon: Icons.camera, phase: 'Phase 5' },
  { id: 'jurisdictions', icon: DsIcons.map, phase: 'Phase 4' },
  { id: 'watchlists', icon: Icons.watchlist, phase: 'Phase 6' },
  { id: 'thresholds', icon: DsIcons.sliders, all: true },
  { id: 'vehicles', icon: Icons.vehicle, phase: 'Phase 7' },
  { id: 'users', icon: Icons.users },
  { id: 'security', icon: DsIcons.lock, all: true },
  { id: 'retention', icon: DsIcons.database },
  { id: 'system', icon: DsIcons.cpu },
]
const sectionsFor = (role) => SECTIONS.filter((s) => s.all || COMMAND.has(role))

const THRESHOLD_UI = {
  confidence_threshold: { label: 'Person detection confidence', step: 0.05, fmt: (v) => `${Math.round(v * 100)}%`, hint: 'Higher = fewer false people, may miss distant ones' },
  weapon_conf_threshold: { label: 'Weapon detection confidence', step: 0.05, fmt: (v) => `${Math.round(v * 100)}%`, hint: 'Higher = fewer false alarms, may miss real weapons' },
  face_tolerance: { label: 'Face match strictness', step: 0.01, fmt: (v) => v.toFixed(2), hint: 'Lower = stricter (fewer wrong matches). Default 0.45' },
  loiter_seconds: { label: 'Loitering time', step: 1, fmt: (v) => `${v}s`, hint: 'Time standing still before it counts as loitering' },
  crowd_threshold: { label: 'Crowd size', step: 1, fmt: (v) => `${v} people`, hint: 'People in one zone before a crowd alert' },
}

const ROLES = [
  { id: 'admin', label: 'Super admin', desc: 'Everything, including users, thresholds and backups.' },
  { id: 'supervisor', label: 'Supervisor', desc: 'Command decisions, escalation, jurisdiction overrides.' },
  { id: 'operator', label: 'Command-centre operator', desc: 'Verifies matches, manages incidents and dispatch.' },
  { id: 'police', label: 'Field officer', desc: 'Alerts and incidents for their cameras; responds and uploads evidence.' },
  { id: 'investigator', label: 'Investigator', desc: 'Evidence, people and vehicle searches for cases.' },
  { id: 'viewer', label: 'Wall display', desc: 'Live picture only; cannot change anything or see personal data.' },
]

const MODEL_LABEL = {
  human_detector: 'Person detection', weapon_detector: 'Weapon detection', vehicle_detector: 'Vehicle detection',
  pose_analyzer: 'Pose / fall checks', fire_detector: 'Fire & smoke detection',
}

/* ——— Sections ——— */

function ProfileSection({ ctx }) {
  const { t, lang, setLang } = useI18n()
  const { theme, setTheme, me } = ctx
  const { push: toast } = useToast()
  const [muted, setMuted] = useState(isAlertSoundMuted)
  return (
    <>
      <Card title="Account">
        <SettingRow label={me?.username || '—'} hint={me?.email || ''}>
          <Badge tone="info" icon={DsIcons.user}>{ROLES.find((r) => r.id === me?.role)?.label || me?.role || '—'}</Badge>
          <button type="button" className="btn btn-sm" onClick={ctx.openProfile}>Edit account</button>
        </SettingRow>
      </Card>
      <Card title="Display">
        <SettingRow label={t('settings.language')} hint="বাংলা / English — saved on this device">
          <Seg value={lang} options={LANGS.map((l) => ({ value: l.id, label: l.label }))}
            onChange={(v) => { setLang(v); toast(v === 'bn' ? 'ভাষা: বাংলা' : 'Language: English', 'ok') }} />
        </SettingRow>
        <SettingRow label={t('settings.theme')} hint="Dark is easier on the eyes in a control room">
          <Seg value={theme} options={[{ value: 'dark', label: t('settings.theme.dark') }, { value: 'light', label: t('settings.theme.light') }]}
            onChange={(v) => { setTheme(v); toast(`Theme: ${v}`, 'ok') }} />
        </SettingRow>
        <SettingRow label={t('settings.sound')} hint="Critical alerts repeat the tone until acknowledged">
          <Seg value={muted ? 'muted' : 'on'} options={[{ value: 'on', label: t('settings.sound.on') }, { value: 'muted', label: t('settings.sound.muted') }]}
            onChange={(v) => { const m = v === 'muted'; setAlertSoundMuted(m); setMuted(m); toast(m ? 'Alert sound muted on this device' : 'Alert sound on', m ? 'warn' : 'ok') }} />
        </SettingRow>
      </Card>
      <Card title="Keyboard shortcuts">
        {[['Command palette', '⌘K / Ctrl+K'], ['Notifications', 'N'], ['Quick answers', 'C'],
          ['Alerts: next / previous', 'J / K'], ['Alerts: confirm / reject', 'V / D']].map(([k, v]) => (
          <SettingRow key={k} label={k}><kbd className="mono">{v}</kbd></SettingRow>
        ))}
      </Card>
    </>
  )
}

function NotificationsSection({ ctx }) {
  if (!COMMAND.has(ctx.me?.role)) return <PersonalAlerts />
  return <ChannelsSection ctx={ctx} />
}

/** What a non-command user controls: this device's sound and phone alerts. */
function PersonalAlerts() {
  const { push: toast } = useToast()
  const [muted, setMuted] = useState(isAlertSoundMuted)
  return (
    <Card title="This device">
      <SettingRow label="Alert sound" hint="Critical alerts repeat the tone until acknowledged">
        <Seg value={muted ? 'muted' : 'on'} options={[{ value: 'on', label: 'On' }, { value: 'muted', label: 'Muted' }]}
          onChange={(v) => { const m = v === 'muted'; setAlertSoundMuted(m); setMuted(m); toast(m ? 'Alert sound muted on this device' : 'Alert sound on', m ? 'warn' : 'ok') }} />
      </SettingRow>
      <SettingRow label="Phone alerts" hint="Turn on from the Responders page on your phone">
        <Badge tone="muted" icon={Icons.bell}>Per device</Badge>
      </SettingRow>
    </Card>
  )
}

function ChannelsSection({ ctx }) {
  const { push: toast } = useToast()
  const [integrations, setIntegrations] = useState(null)
  const [error, setError] = useState('')
  const [testing, setTesting] = useState(null)
  const load = () => fetchIntegrationStatus()
    .then((d) => { setIntegrations(d); setError('') })
    .catch((e) => setError(e.message || 'Could not load channels'))
  useEffect(() => { load() }, [])

  const runTest = async (channel) => {
    setTesting(channel)
    try {
      const r = await testIntegration(channel, `Aegis test from ${channel}`)
      toast(`${channel}: test sent (HTTP ${r.http_status})`, 'ok')
    } catch (e) {
      toast(`${channel}: ${e.message || 'test failed'}`, 'danger')
    } finally {
      setTesting(null)
    }
  }
  const cams = Object.keys(ctx.systemStatus?.cameras || {}).length

  return (
    <>
      <Card title="Outside channels" sub="CAD, SMS, radio and law-enforcement webhooks">
        {error && <ErrorState compact message={error} onRetry={load} />}
        {!error && !integrations && <div style={{ display: 'grid', gap: 10 }}><Skeleton h={20} /><Skeleton h={20} w="70%" /></div>}
        {integrations && (
          <>
            <SettingRow label="Outside alerts" hint="ALERTS_ENABLED in .env">
              <Badge tone={integrations.alerts_enabled ? 'ok' : 'warn'} icon={integrations.alerts_enabled ? Icons.check : Icons.alert}>
                {integrations.alerts_enabled ? 'Enabled' : 'Disabled'}
              </Badge>
            </SettingRow>
            {Object.entries(integrations.channels || {}).map(([name, ch]) => (
              <SettingRow key={name} label={name} hint={ch.url_host || 'No URL set'}>
                <Badge tone={ch.configured ? 'ok' : 'muted'}>{ch.configured ? 'Configured' : 'Not set'}</Badge>
                {ch.configured && (
                  <button type="button" className="btn btn-sm" disabled={testing === name} onClick={() => runTest(name)}>
                    {testing === name ? 'Sending…' : 'Send test'}
                  </button>
                )}
              </SettingRow>
            ))}
            <p className="ds-setting-hint" style={{ marginTop: 10 }}>
              Set CAD_WEBHOOK, SMS_WEBHOOK, LAW_ENFORCEMENT_WEBHOOK in .env and ALERTS_ENABLED=true.
            </p>
          </>
        )}
      </Card>
      <Card title="Alert rules" sub="Fixed safeguards; not switchable">
        <SettingRow label="Watchlist match → outside notification"><Badge tone="info" icon={Icons.shield}>After operator confirms</Badge></SettingRow>
        <SettingRow label="Weapon and fire alerts"><Badge tone="info">Multi-frame confirmed</Badge></SettingRow>
        <SettingRow label="Incident for critical / high alerts"><Badge tone="ok" icon={Icons.check}>Automatic</Badge></SettingRow>
        <SettingRow label="Camera heartbeat">
          <Badge tone={cams ? 'ok' : 'warn'}>{cams ? `${cams} reporting` : 'No camera reporting'}</Badge>
        </SettingRow>
      </Card>
    </>
  )
}

function LinkOut({ ctx, page, label }) {
  if (!canViewPage(ctx.me?.role, page)) return null
  return <button type="button" className="btn btn-sm btn-primary" onClick={() => ctx.setPage(page)}>{label}</button>
}

function CamerasSection({ ctx }) {
  const list = ctx.camList || []
  const reporting = Object.keys(ctx.systemStatus?.cameras || {}).length
  return (
    <>
      <Card title="Camera registry" actions={<LinkOut ctx={ctx} page="cameras" label="Manage cameras" />}>
        <SettingRow label="Registered cameras"><b>{list.length}</b></SettingRow>
        <SettingRow label="Sending a heartbeat now"><Badge tone={reporting ? 'ok' : 'warn'}>{reporting}</Badge></SettingRow>
      </Card>
      <Card>
        <EmptyState compact icon={Icons.camera} title="Nationwide camera registry">
          Protocol, encrypted credentials, thana, road, heading arrow on a map, capabilities and CSV import come in Phase 5.
        </EmptyState>
      </Card>
    </>
  )
}

function ComingSection({ icon, title, children, ctx, link }) {
  return (
    <Card>
      <EmptyState icon={icon} title={title} action={link && <LinkOut ctx={ctx} page={link.page} label={link.label} />}>
        {children}
      </EmptyState>
    </Card>
  )
}

function ThresholdsSection({ ctx, drafts, setDrafts, values, setValues }) {
  const canEdit = ctx.me?.role === 'admin'
  const { t } = useI18n()
  const [specs, setSpecs] = useState(null)
  const [error, setError] = useState('')
  const load = () => {
    Promise.all([fetchThresholdSpecs(), fetchConfigThresholds()]).then(([sp, v]) => {
      setSpecs(sp)
      setError('')
      setValues(Object.fromEntries(Object.entries(v).map(([k, x]) => [k, parseFloat(x)])))
    }).catch((e) => setError(e.message || 'Could not load thresholds'))
  }
  useEffect(() => { load() }, [])   // eslint-disable-line react-hooks/exhaustive-deps
  // A draft equal to the saved value is not a change.
  const setDraft = (k, v, saved) => setDrafts((d) => {
    const next = { ...d }
    if (v === saved) delete next[k]; else next[k] = v
    return next
  })

  return (
    <Card title="Live thresholds" sub={canEdit ? 'Applied to every camera; every change is audit-logged' : t('settings.readonly')}>
      {error && <ErrorState compact message={error} onRetry={load} />}
      {!error && !specs && <div style={{ display: 'grid', gap: 18 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={34} />)}</div>}
      {specs && Object.keys(THRESHOLD_UI).filter((k) => specs[k]).map((k) => {
        const ui = THRESHOLD_UI[k]
        const spec = specs[k]
        const saved = values[k] ?? spec.default
        const shown = drafts[k] ?? saved
        const dirty = k in drafts
        return (
          <div className="ds-slider" key={k}>
            <div className="ds-slider-top">
              <label htmlFor={`thr-${k}`}>{ui.label}</label>
              <span className={`ds-slider-value ${dirty ? 'dirty' : ''}`}>{dirty && <>{ui.fmt(saved)} → </>}{ui.fmt(shown)}</span>
            </div>
            <input id={`thr-${k}`} type="range" min={spec.min} max={spec.max} step={ui.step} value={shown} disabled={!canEdit}
              aria-describedby={`thr-${k}-hint`}
              onChange={(e) => setDraft(k, Number(e.target.value), saved)} />
            <span className="ds-slider-hint" id={`thr-${k}-hint`}>
              {ui.hint}
              {canEdit && shown !== spec.default && (
                <> · <button type="button" className="link-btn" onClick={() => setDraft(k, spec.default, saved)}>Reset to {ui.fmt(spec.default)}</button></>
              )}
            </span>
          </div>
        )
      })}
    </Card>
  )
}

function UsersSection({ ctx }) {
  return (
    <Card title="Roles" sub="What each role may do; enforced by the server" actions={<LinkOut ctx={ctx} page="users" label="Manage users" />}>
      {ROLES.map((r) => (
        <SettingRow key={r.id} label={r.label} hint={r.desc}>
          {ctx.me?.role === r.id && <Badge tone="info" icon={DsIcons.user}>You</Badge>}
        </SettingRow>
      ))}
    </Card>
  )
}

function SecuritySection() {
  return (
    <>
      <Card title="Two-step sign-in"><TwoFactor /></Card>
      <Card title="Session">
        <SettingRow label="Sign-in tokens" hint="Changing your password signs out every other device"><Badge tone="ok" icon={Icons.check}>Revocable</Badge></SettingRow>
        <SettingRow label="Failed sign-ins" hint="Repeated wrong passwords lock the account for a while"><Badge tone="ok" icon={Icons.check}>Lockout on</Badge></SettingRow>
        <SettingRow label="Evidence at rest" hint="Images and evidence stored encrypted"><Badge tone="ok" icon={DsIcons.lock}>Encrypted</Badge></SettingRow>
      </Card>
    </>
  )
}

function RetentionSection({ ctx }) {
  const isAdmin = ctx.me?.role === 'admin'
  const { push: toast } = useToast()
  const [info, setInfo] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = () => {
    if (!isAdmin) return
    fetchBackups().then((d) => { setInfo(d); setError('') }).catch((e) => setError(e.message || 'Could not load backups'))
  }
  useEffect(() => { load() }, [isAdmin])   // eslint-disable-line react-hooks/exhaustive-deps
  const now = async () => {
    setBusy(true)
    try {
      const b = await runBackupNow()
      toast(`Backup ${b.name} saved (${(b.bytes / 1e6).toFixed(1)} MB)`, 'ok')
      setInfo(await fetchBackups())
    } catch (e) {
      toast(e.message || 'Backup failed', 'danger')
    } finally {
      setBusy(false)
    }
  }
  const last = info?.backups?.[0]
  return (
    <>
      <Card title="What is kept, and for how long">
        <SettingRow label="Recordings" hint="DVR_RETENTION_HOURS on the server"><Badge tone="muted" icon={Icons.clock}>Rolling</Badge></SettingRow>
        <SettingRow label="Evidence in open incidents" hint="Never removed while the case is open"><Badge tone="ok" icon={DsIcons.lock}>Kept whole</Badge></SettingRow>
        <SettingRow label="Evidence images after the window" hint="Record and custody chain stay; the image is removed"><Badge tone="muted">Scheduled</Badge></SettingRow>
        <SettingRow label="Non-matched detections & plate reads" hint="Editable policy per data type in Phase 14"><Badge tone="warn">{'Coming'}</Badge></SettingRow>
      </Card>
      <Card title="Backups and clean-up" sub={`Every night at ${String(info?.maintenance_hour ?? 3).padStart(2, '0')}:00`}
        actions={isAdmin && <button type="button" className="btn btn-sm" disabled={busy} onClick={now}>{busy ? 'Backing up…' : 'Back up now'}</button>}>
        {!isAdmin && <p className="ds-setting-hint">Only an admin can see and run backups.</p>}
        {isAdmin && error && <ErrorState compact message={error} onRetry={load} />}
        {isAdmin && !error && !info && <Skeleton h={60} />}
        {isAdmin && info && (
          <>
            <SettingRow label="Last backup">{last ? `${timeAgo(last.created_at)} · ${(last.bytes / 1e6).toFixed(1)} MB` : 'None yet'}</SettingRow>
            <SettingRow label="Kept">{`${info.backups.length} of the last ${info.keep}`}</SettingRow>
            <SettingRow label="Folder"><span className="mono" style={{ wordBreak: 'break-all' }}>{info.folder}</span></SettingRow>
          </>
        )}
      </Card>
    </>
  )
}

function SystemSection({ ctx }) {
  const models = ctx.systemStatus?.models
  const redis = ctx.systemStatus?.redis
  return (
    <div className="settings-grid">
      <Card title="AI models" sub="What is actually running">
        {!models && <EmptyState compact icon={DsIcons.cpu} title="Status unavailable">The pipeline has not reported yet.</EmptyState>}
        {models && Object.entries(models).map(([key, status]) => (
          <SettingRow key={key} label={MODEL_LABEL[key] || key}>
            <Badge tone={status === 'ok' ? 'ok' : status === 'missing' ? 'danger' : 'muted'} icon={status === 'ok' ? Icons.check : status === 'missing' ? Icons.alert : DsIcons.dot}>
              {status === 'ok' ? 'Loaded' : status === 'missing' ? 'Model file missing' : status === 'disabled' ? 'Off in config.yaml' : 'Not installed'}
            </Badge>
          </SettingRow>
        ))}
      </Card>
      <Card title="API & storage">
        <SettingRow label="REST"><span className="mono">/api/v1</span></SettingRow>
        <SettingRow label="API docs"><a href="/docs" target="_blank" rel="noreferrer" className="link-btn">/docs</a></SettingRow>
        <SettingRow label="Evidence">SHA-256 custody chain</SettingRow>
        <SettingRow label="Shared state">
          <Badge tone={redis?.connected ? 'ok' : redis?.enabled ? 'danger' : 'muted'}>
            {redis?.connected ? 'Redis connected' : redis?.enabled ? 'Redis down' : 'Single server'}
          </Badge>
        </SettingRow>
      </Card>
    </div>
  )
}

/* ——— Page ——— */

export function Settings({ ctx }) {
  const { t } = useI18n()
  const { push: toast } = useToast()
  const [ask, confirmDialog] = useConfirm()
  const sections = sectionsFor(ctx.me?.role)
  const [picked, setSection] = useState(() => sessionStorage.getItem(SECTION_KEY) || 'profile')
  const section = sections.some((x) => x.id === picked) ? picked : 'profile'
  // Threshold drafts live here so the save bar and the leave-section guard can see them.
  const [values, setValues] = useState({})
  const [drafts, setDrafts] = useState({})
  const [saving, setSaving] = useState(false)
  const dirty = Object.keys(drafts).length

  const go = async (id) => {
    if (id === section) return
    if (dirty && !(await ask({ title: t('common.unsavedTitle'), message: t('common.unsavedLeave'), confirmLabel: t('common.discard'), danger: true }))) return
    setDrafts({})
    setSection(id)
    sessionStorage.setItem(SECTION_KEY, id)
  }

  const save = async () => {
    setSaving(true)
    const entries = Object.entries(drafts)
    const results = await Promise.allSettled(entries.map(([k, v]) => saveConfigThreshold(k, v)))
    const ok = entries.filter((_, i) => results[i].status === 'fulfilled')
    const failed = results.filter((r) => r.status === 'rejected')
    setValues((prev) => ({ ...prev, ...Object.fromEntries(ok) }))
    setDrafts((d) => {
      const next = { ...d }
      ok.forEach(([k]) => delete next[k])
      return next
    })
    setSaving(false)
    if (!failed.length) toast(t('settings.saved'), 'ok')
    else toast(t('settings.savedSome', { ok: ok.length, n: entries.length, fail: failed[0].reason?.message || '' }), 'danger')
  }

  const discard = () => { setDrafts({}); toast(t('common.discarded'), 'info') }

  const current = sections.find((s) => s.id === section)
  const renderBody = () => {
    switch (section) {
      case 'profile': return <ProfileSection ctx={ctx} />
      case 'notifications': return <NotificationsSection ctx={ctx} />
      case 'cameras': return <CamerasSection ctx={ctx} />
      case 'jurisdictions': return (
        <ComingSection ctx={ctx} icon={DsIcons.map} title="Jurisdictions arrive in Phase 4">
          Division → district → thana boundaries on a map, and the officers covering each. Alerts and the officer
          picker will only offer officers whose area contains the camera.
        </ComingSection>
      )
      case 'watchlists': return (
        <ComingSection ctx={ctx} icon={Icons.watchlist} title="Watchlist governance arrives in Phase 6" link={{ page: 'faces', label: 'Open People' }}>
          Case/FIR/GD number, legal basis, second-person approval and an expiry date on every entry; expired entries
          stop alerting on their own.
        </ComingSection>
      )
      case 'thresholds': return <ThresholdsSection ctx={ctx} drafts={drafts} setDrafts={setDrafts} values={values} setValues={setValues} />
      case 'vehicles': return (
        <ComingSection ctx={ctx} icon={Icons.vehicle} title="Vehicle lists arrive in Phase 7" link={{ page: 'vehicles', label: 'Open Vehicles' }}>
          Managed lists of vehicle types (CNG, leguna, easy-bike…), colours and make/model, plus matching weights.
        </ComingSection>
      )
      case 'users': return <UsersSection ctx={ctx} />
      case 'security': return <SecuritySection />
      case 'retention': return <RetentionSection ctx={ctx} />
      default: return <SystemSection ctx={ctx} />
    }
  }

  return (
    <div className="settings-shell">
      <nav className="ds-nav" aria-label={t('settings.nav')}>
        {sections.map(({ id, icon: Icon, phase }) => (
          <button key={id} type="button" className="ds-nav-item" aria-current={id === section ? 'page' : undefined} onClick={() => go(id)}>
            <Icon aria-hidden="true" /> {t(`settings.${id}`)}
            {phase && <span className="ds-nav-soon">{phase}</span>}
          </button>
        ))}
      </nav>
      <section className="settings-content" aria-labelledby="settings-section-title">
        <SectionHeader id="settings-section-title" icon={current.icon} title={t(`settings.${section}`)} desc={t(`settings.${section}.desc`)} />
        {renderBody()}
        <SaveBar count={dirty} busy={saving} onSave={save} onDiscard={discard} />
      </section>
      {confirmDialog}
    </div>
  )
}
