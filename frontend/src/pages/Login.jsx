import React, { useState } from 'react'
import { api, auth } from '../api'
import { Msg } from '../ui'

export default function Login({ onIn }) {
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async e => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      const r = await api('/auth/login', { method: 'POST', body: { username: u, password: p } })
      auth.set(r.token)
      onIn(r.user)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="login">
      <form onSubmit={submit} className="panel">
        <div className="brand"><span className="brand-mark" aria-hidden="true" />Loan Ledger</div>
        <Msg error={err} />
        <label className="f">Username<input value={u} onChange={e => setU(e.target.value)} autoComplete="username" autoFocus required /></label>
        <label className="f">Password<input type="password" value={p} onChange={e => setP(e.target.value)} autoComplete="current-password" required /></label>
        <button className="btn" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  )
}
