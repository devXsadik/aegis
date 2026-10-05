import { useEffect, useState } from 'react'
import { Card, Icons, Tag, Empty, timeAgo } from '../components/ui'
import { fetchUsers, createUser } from '../services/api'

const ROLE_TONE = { admin: 'danger', supervisor: 'orange', police: 'info', operator: 'ok', investigator: 'purple', viewer: 'muted' }

const ROLES = [
  { role: 'admin', label: 'Administrator', perms: 'Full system control · users · watchlist · audit · settings' },
  { role: 'supervisor', label: 'Supervisor', perms: 'Incident oversight · assign officers · verify alerts · reports' },
  { role: 'police', label: 'Police', perms: 'Receive dispatches · live GPS pins · update incident status' },
  { role: 'operator', label: 'Operator', perms: 'Live monitoring · alert triage · evidence viewing · reports' },
  { role: 'investigator', label: 'Investigator', perms: 'Evidence deep-dive · watchlist queries · vehicle history' },
]

export function Users({ ctx }) {
  const { auditLogs, me } = ctx
  const [users, setUsers] = useState(null)
  const [form, setForm] = useState({ username: '', email: '', password: '', role: 'operator', phone: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const isAdmin = me?.role === 'admin'

  const load = () => fetchUsers().then(setUsers).catch(() => setUsers(null))
  useEffect(() => { load() }, [])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setMsg(null)
    try {
      await createUser(form)
      setMsg({ ok: true, text: `User "${form.username}" created` })
      setForm({ username: '', email: '', password: '', role: 'operator', phone: '' })
      load()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="grid grid-23" style={{ marginBottom: 14 }}>
        <Card title="System Users" sub={users ? `${users.length} accounts` : 'admin access required'} flush={!!users?.length}>
          {!users && <Empty icon={Icons.users}>User list requires an administrator session</Empty>}
          {users && users.length === 0 && <Empty icon={Icons.users}>No users — run <code>python scripts/seed_demo.py</code></Empty>}
          {users && users.length > 0 && (
            <table className="table">
              <thead><tr><th>User</th><th>Email</th><th>Role</th><th>Status</th></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td><b>{u.username}</b>{me?.id === u.id && <span className="muted"> (you)</span>}</td>
                    <td className="muted">{u.email}</td>
                    <td><Tag tone={ROLE_TONE[u.role] || 'muted'}>{u.role}</Tag></td>
                    <td><Tag tone={u.is_active ? 'ok' : 'muted'}>{u.is_active ? 'Active' : 'Disabled'}</Tag></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Create User" sub={isAdmin ? 'admin only' : 'requires admin role'}>
          {msg && (
            <div className={msg.ok ? 'tag tag-ok' : 'login-error'} style={{ marginBottom: 10, display: 'block', padding: '8px 12px' }}>
              {msg.text}
            </div>
          )}
          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <label className="field">Username
              <input className="input" required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
            </label>
            <label className="field">Email
              <input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </label>
            <label className="field">Password
              <input className="input" type="password" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </label>
            <label className="field">Phone (for police SMS alerts, e.g. +8801XXXXXXXXX)
              <input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </label>
            <label className="field">Role
              <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {ROLES.map((r) => <option key={r.role} value={r.role}>{r.label}</option>)}
              </select>
            </label>
            <button className="btn btn-primary" type="submit" disabled={busy || !isAdmin}>
              <Icons.users /> {busy ? 'Creating…' : 'Create User'}
            </button>
          </form>
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Role-Based Access Control" sub="enforced by backend JWT">
          {ROLES.map((r) => (
            <div key={r.role} className="row" style={{ alignItems: 'flex-start' }}>
              <div>
                <Tag tone={ROLE_TONE[r.role]}>{r.label}</Tag>
                <div className="meta" style={{ marginTop: 6 }}>{r.perms}</div>
              </div>
            </div>
          ))}
        </Card>

        <Card title="Audit Trail" sub="admin-only · latest activity">
          {(!auditLogs || auditLogs.length === 0) && (
            <Empty icon={Icons.shield}>No audit entries visible — requires an administrator session</Empty>
          )}
          {(auditLogs || []).slice(0, 15).map((log) => (
            <div key={log.id} className="row">
              <div>
                <b style={{ fontSize: '0.83rem' }}>{log.action}</b>
                <div className="meta">{log.username || 'system'} · {log.resource || ''} {log.resource_id || ''}</div>
              </div>
              <span className="muted" style={{ fontSize: '0.74rem' }}>{timeAgo(log.timestamp)}</span>
            </div>
          ))}
        </Card>
      </div>
    </>
  )
}
