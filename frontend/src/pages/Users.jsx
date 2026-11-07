import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Msg } from '../ui'
import { useUser } from '../main'

const ROLES = [
  ['VIEWER', 'Viewer', 'Views loans and customers, and downloads single-loan documents: SOA, foreclosure PDF, DPD.'],
  ['REPORTER', 'Reporter', 'Everything a viewer can do, plus the dues report, the Excel download and the data exports.'],
  ['OPS', 'Operations', 'Books loans, posts payments and charges, and uploads files. Reports and exports included.'],
  ['ADMIN', 'Admin', 'Configuration (products, migration, data tools) and user management. Everything else.'],
]
const roleLabel = r => (ROLES.find(x => x[0] === r) || [r, r])[1]

export default function Users() {
  const me = useUser()
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [f, setF] = useState({ username: '', full_name: '', password: '', role: 'VIEWER' })
  const load = () => api('/users').then(setRows).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])

  const create = async e => {
    e.preventDefault(); setErr(''); setOk('')
    try {
      await api('/users', { method: 'POST', body: f })
      setOk(`User ${f.username} created as ${roleLabel(f.role)}.`)
      setF({ username: '', full_name: '', password: '', role: 'VIEWER' })
      load()
    } catch (e2) { setErr(e2.message) }
  }
  const update = async (u, changes) => {
    setErr(''); setOk('')
    try { await api(`/users/${u.id}`, { method: 'PUT', body: changes }); setOk(`${u.username} updated.`); load() } catch (e2) { setErr(e2.message) }
  }
  const resetPassword = u => {
    const pw = window.prompt(`New password for ${u.username} (at least 8 characters)`)
    if (pw) update(u, { password: pw })
  }

  return (
    <>
      <div className="head"><div><h1>Users</h1><div className="sub">Who can sign in, and what they can do.</div></div></div>
      <Msg error={err} ok={ok} />
      <section className="panel flush"><div className="table-wrap"><table>
        <thead><tr><th>User</th><th>Name</th><th>Role</th><th>Active</th><th></th></tr></thead>
        <tbody>
          {rows?.map(u => (
            <tr key={u.id}>
              <td>{u.username}</td><td>{u.full_name || '—'}</td>
              <td>
                <select value={u.role} onChange={e => update(u, { role: e.target.value })} aria-label={`Role for ${u.username}`}>
                  {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </td>
              <td>
                <label className="small"><input type="checkbox" checked={u.active} disabled={u.username === me.username}
                  onChange={e => update(u, { active: e.target.checked })} /> {u.active ? 'Active' : 'Blocked'}</label>
              </td>
              <td><button className="btn ghost small" onClick={() => resetPassword(u)}>Reset password</button></td>
            </tr>
          ))}
        </tbody>
      </table></div></section>

      <section className="panel">
        <h2>Add a user</h2>
        <form onSubmit={create}>
          <div className="form">
            <label className="f">Username<input value={f.username} onChange={e => setF({ ...f, username: e.target.value })} required minLength={3} /></label>
            <label className="f">Full name<input value={f.full_name} onChange={e => setF({ ...f, full_name: e.target.value })} /></label>
            <label className="f">Password<input type="password" value={f.password} onChange={e => setF({ ...f, password: e.target.value })} required minLength={8} /></label>
            <label className="f">Role<select value={f.role} onChange={e => setF({ ...f, role: e.target.value })}>
              {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select></label>
          </div>
          <p className="small muted">{ROLES.find(r => r[0] === f.role)[2]}</p>
          <div className="row end"><button className="btn">Add user</button></div>
        </form>
      </section>
    </>
  )
}
