import React, { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, money, fmtDate } from '../api'
import { Msg, Modal, Tag, FieldGroups, Fields } from '../ui'
import { useUser } from '../main'

export default function Customers() {
  const user = useUser()
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState('')
  const [data, setData] = useState(null)
  const [sel, setSel] = useState(null)
  const [adding, setAdding] = useState(false)
  const [err, setErr] = useState('')
  const load = (query = q) => api('/customers', { params: { q: query, limit: 100 } }).then(setData).catch(e => setErr(e.message))
  useEffect(() => { load('') }, [])
  const id = sp.get('id')
  useEffect(() => { if (id) api(`/customers/${id}`).then(setSel).catch(e => setErr(e.message)); else setSel(null) }, [id])

  return (
    <>
      <div className="head">
        <div><h1>Customers</h1>{data && <div className="sub">{data.total} borrowers</div>}</div>
        {(user.role === 'ADMIN' || user.role === 'OPS') && <button className="btn" onClick={() => setAdding(true)}>Add borrower</button>}
      </div>
      <Msg error={err} />
      {sel && (
        <section className="panel">
          <div className="row"><h2 style={{ margin: 0 }}>{sel.name}</h2><div className="spacer" /><button className="btn ghost small" onClick={() => setSp({})}>Close</button></div>
          <p className="muted small" style={{ marginTop: '.25rem' }}>{[sel.mobile, sel.email, sel.pan, sel.external_ref && `Customer ID ${sel.external_ref}`].filter(Boolean).join(', ')}</p>
          <div style={{ margin: '.75rem 0' }}><Fields items={[['Address', sel.address || '—']]} /></div>
          <FieldGroups groups={sel.client_groups} />
          <div className="table-wrap"><table>
            <thead><tr><th>Loan</th><th className="n">Loan amount</th><th className="n">EMI</th><th className="n">Tenure</th><th>Disbursed</th><th>Last repayment</th><th>Origin</th><th>Status</th></tr></thead>
            <tbody>{sel.loans.map(l => <tr key={l.id}><td><Link to={`/loans/${l.id}`}>{l.loan_number}</Link></td><td className="n">{money(l.principal)}</td><td className="n">{money(l.emi_amount)}</td><td className="n">{l.tenure_months} m</td><td>{fmtDate(l.disbursal_date)}</td><td>{fmtDate(l.last_due_date)}</td><td>{l.source === 'M2P' ? 'M2P' : 'Booked here'}</td><td><Tag>{l.status}</Tag></td></tr>)}
              {sel.loans.length === 0 && <tr><td colSpan={8} className="muted">No loans yet.</td></tr>}</tbody>
          </table></div>
        </section>
      )}
      <form className="row" style={{ marginBottom: '1rem' }} onSubmit={e => { e.preventDefault(); load() }}>
        <input placeholder="Name, mobile, PAN or M2P id" value={q} onChange={e => setQ(e.target.value)} style={{ width: 300 }} aria-label="Search customers" />
        <button className="btn ghost">Search</button>
      </form>
      <div className="panel flush"><div className="table-wrap"><table>
        <thead><tr><th>Name</th><th>Mobile</th><th>PAN</th><th>Email</th><th>M2P id</th></tr></thead>
        <tbody>
          {data?.items.length === 0 && <tr><td colSpan={5} className="empty">No borrowers found.</td></tr>}
          {data?.items.map(c => (
            <tr key={c.id} className="click" onClick={() => setSp({ id: c.id })}><td>{c.name}</td><td>{c.mobile || '—'}</td><td>{c.pan || '—'}</td><td>{c.email || '—'}</td><td>{c.external_ref || '—'}</td></tr>
          ))}
        </tbody>
      </table></div></div>
      {adding && <AddCustomer onClose={() => setAdding(false)} onDone={c => { setAdding(false); load(); setSp({ id: c.id }) }} />}
    </>
  )
}

function AddCustomer({ onClose, onDone }) {
  const [f, setF] = useState({ name: '', mobile: '', email: '', pan: '', address: '' })
  const [err, setErr] = useState('')
  const set = k => e => setF({ ...f, [k]: k === 'pan' ? e.target.value.toUpperCase() : e.target.value })
  const submit = async e => {
    e.preventDefault()
    const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v || null]))
    try { onDone(await api('/customers', { method: 'POST', body })) } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title="Add borrower" onClose={onClose}>
      <form onSubmit={submit}>
        <div className="form">
          <label className="f">Full name<input value={f.name} onChange={set('name')} required autoFocus /></label>
          <label className="f">Mobile<input value={f.mobile} onChange={set('mobile')} /></label>
          <label className="f">PAN<input value={f.pan} onChange={set('pan')} maxLength={10} placeholder="ABCDE1234F" /></label>
          <label className="f">Email<input type="email" value={f.email} onChange={set('email')} /></label>
          <label className="f wide">Address<textarea rows={2} value={f.address} onChange={set('address')} /></label>
        </div>
        <Msg error={err} />
        <div className="row end" style={{ marginTop: '1rem' }}><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn">Add borrower</button></div>
      </form>
    </Modal>
  )
}
