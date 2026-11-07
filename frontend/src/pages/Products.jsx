import React, { useEffect, useState } from 'react'
import { api, money } from '../api'
import { Msg, Modal, Tag } from '../ui'
import { useUser } from '../main'

const BLANK = { code: '', name: '', interest_method: 'REDUCING', default_rate: 18, min_tenure: 3, max_tenure: 60, min_amount: 10000, max_amount: 2500000,
  apportion_mode: 'HEAD_WISE', excess_mode: 'HOLD', late_fee: 500, grace_days: 3, bounce_charge: 590, foreclosure_fee_pct: 4, processing_fee_pct: 2, active: true }

export default function Products() {
  const user = useUser()
  const [rows, setRows] = useState(null)
  const [edit, setEdit] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api('/products').then(setRows).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])
  const admin = user.role === 'ADMIN'
  return (
    <>
      <div className="head">
        <div><h1>Loan products</h1><div className="sub">Each product sets the schedule type, the payment waterfall and the charges for loans booked on it.</div></div>
        {admin && <button className="btn" onClick={() => setEdit(BLANK)}>Add product</button>}
      </div>
      <Msg error={err} />
      <div className="panel flush"><div className="table-wrap"><table>
        <thead><tr><th>Product</th><th>Schedule</th><th className="n">Rate</th><th className="n">Amount range</th><th className="n">Tenure</th><th>Waterfall</th><th className="n">Late fee</th><th className="n">Bounce</th><th className="n">Foreclosure</th><th /></tr></thead>
        <tbody>
          {rows?.map(p => (
            <tr key={p.id}>
              <td><strong>{p.name}</strong><div className="small muted">{p.code}</div></td>
              <td>{p.interest_method === 'FLAT' ? 'Flat' : 'Reducing'}</td>
              <td className="n">{Number(p.default_rate)}%</td>
              <td className="n">{money(p.min_amount)}<br />{money(p.max_amount)}</td>
              <td className="n">{p.min_tenure}–{p.max_tenure} mo</td>
              <td className="small">{p.apportion_mode === 'HEAD_WISE' ? 'All interest, then principal' : 'Oldest EMI first'}, then charges.<br />Excess {p.excess_mode === 'HOLD' ? 'held to next due date' : 'pre-pays future EMIs'}.</td>
              <td className="n">{money(p.late_fee)}<div className="small muted">after {p.grace_days} days</div></td>
              <td className="n">{money(p.bounce_charge)}</td>
              <td className="n">{Number(p.foreclosure_fee_pct)}%</td>
              <td>{!p.active && <Tag>Inactive</Tag>}{admin && <button className="btn ghost small" onClick={() => setEdit(p)}>Edit</button>}</td>
            </tr>
          ))}
        </tbody>
      </table></div></div>
      <p className="small muted">Changing a product affects loans booked after the change. Loans already booked keep the waterfall they were booked with.</p>
      {edit && <ProductForm initial={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); load() }} />}
    </>
  )
}

function ProductForm({ initial, onClose, onDone }) {
  const [f, setF] = useState(initial)
  const [err, setErr] = useState('')
  const set = k => e => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const submit = async e => {
    e.preventDefault()
    const body = { ...f }; delete body.id
    for (const k of ['min_tenure', 'max_tenure', 'grace_days']) body[k] = Number(body[k])
    try {
      await api(f.id ? `/products/${f.id}` : '/products', { method: f.id ? 'PUT' : 'POST', body })
      onDone()
    } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title={f.id ? `Edit ${f.code}` : 'Add product'} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="form">
          <label className="f">Code<input value={f.code} onChange={set('code')} required disabled={!!f.id} /></label>
          <label className="f">Name<input value={f.name} onChange={set('name')} required /></label>
          <label className="f">Schedule<select value={f.interest_method} onChange={set('interest_method')}><option value="REDUCING">Reducing balance EMI</option><option value="FLAT">Flat rate</option></select></label>
          <label className="f">Default rate (%)<input type="number" step="0.01" value={f.default_rate} onChange={set('default_rate')} /></label>
          <label className="f">Min amount<input type="number" value={f.min_amount} onChange={set('min_amount')} /></label>
          <label className="f">Max amount<input type="number" value={f.max_amount} onChange={set('max_amount')} /></label>
          <label className="f">Min tenure (months)<input type="number" value={f.min_tenure} onChange={set('min_tenure')} /></label>
          <label className="f">Max tenure (months)<input type="number" value={f.max_tenure} onChange={set('max_tenure')} /></label>
          <label className="f wide">Payment waterfall<select value={f.apportion_mode} onChange={set('apportion_mode')}>
            <option value="HEAD_WISE">All overdue interest, then all overdue principal, then charges</option>
            <option value="INSTALLMENT_WISE">Oldest EMI first (its interest, then principal), then charges</option>
          </select></label>
          <label className="f wide">Money left over<select value={f.excess_mode} onChange={set('excess_mode')}>
            <option value="HOLD">Hold as excess, adjust on next due date</option>
            <option value="ADVANCE">Apply to future EMIs straight away</option>
          </select></label>
          <label className="f">Late fee (₹)<input type="number" value={f.late_fee} onChange={set('late_fee')} /></label>
          <label className="f">Grace days<input type="number" value={f.grace_days} onChange={set('grace_days')} /></label>
          <label className="f">Bounce charge (₹)<input type="number" value={f.bounce_charge} onChange={set('bounce_charge')} /></label>
          <label className="f">Foreclosure charge (%)<input type="number" step="0.01" value={f.foreclosure_fee_pct} onChange={set('foreclosure_fee_pct')} /></label>
          <label className="f">Processing fee (%)<input type="number" step="0.01" value={f.processing_fee_pct} onChange={set('processing_fee_pct')} /></label>
          <label className="row small"><input type="checkbox" checked={f.active} onChange={set('active')} /> Available for new loans</label>
        </div>
        <Msg error={err} />
        <div className="row end" style={{ marginTop: '1rem' }}><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn">Save product</button></div>
      </form>
    </Modal>
  )
}
