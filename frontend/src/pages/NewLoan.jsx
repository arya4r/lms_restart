import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, money, fmtDate, today } from '../api'
import { Msg } from '../ui'

export default function NewLoan() {
  const nav = useNavigate()
  const [products, setProducts] = useState([])
  const [custQ, setCustQ] = useState('')
  const [custs, setCusts] = useState([])
  const [cust, setCust] = useState(null)
  const [newCust, setNewCust] = useState(null)
  const [f, setF] = useState({ product_id: '', principal: '', annual_rate: '', tenure_months: 12, disbursal_date: today(), first_due_date: '' })
  const [prev, setPrev] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api('/products').then(ps => {
      const act = ps.filter(p => p.active && p.interest_method !== 'LEASE_3W'); setProducts(act)
      if (act[0]) setF(x => ({ ...x, product_id: act[0].id, annual_rate: act[0].default_rate }))
    }).catch(e => setErr(e.message))
  }, [])
  useEffect(() => {
    if (custQ.length < 2) { setCusts([]); return }
    const t = setTimeout(() => api('/customers', { params: { q: custQ, limit: 8 } }).then(r => setCusts(r.items)), 250)
    return () => clearTimeout(t)
  }, [custQ])

  const product = products.find(p => String(p.id) === String(f.product_id))
  const set = k => e => { setPrev(null); setF({ ...f, [k]: e.target.value }) }
  const body = () => ({ ...f, product_id: Number(f.product_id), tenure_months: Number(f.tenure_months), annual_rate: f.annual_rate === '' ? null : f.annual_rate, first_due_date: f.first_due_date || null })

  const preview = async e => {
    e.preventDefault(); setErr('')
    try { setPrev(await api('/loans/preview-schedule', { method: 'POST', body: body() })) } catch (e) { setErr(e.message) }
  }
  const book = async () => {
    setBusy(true); setErr('')
    try {
      let c = cust
      if (!c && newCust) c = await api('/customers', { method: 'POST', body: { ...newCust, pan: newCust.pan || null, email: newCust.email || null } })
      if (!c) throw new Error('Choose a borrower or add a new one')
      const loan = await api('/loans', { method: 'POST', body: { ...body(), customer_id: c.id } })
      nav(`/loans/${loan.id}`)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <>
      <div className="head"><div><h1>Book a loan</h1><div className="sub">New loans use the Interest, then Principal, then Charges waterfall set on the product.</div></div></div>
      <Msg error={err} />
      <section className="panel">
        <h2>Borrower</h2>
        {cust ? (
          <div className="row"><strong>{cust.name}</strong><span className="muted">{cust.mobile}</span><button className="btn ghost small" onClick={() => setCust(null)}>Change</button></div>
        ) : newCust ? (
          <div className="form">
            <label className="f">Full name<input value={newCust.name} onChange={e => setNewCust({ ...newCust, name: e.target.value })} required /></label>
            <label className="f">Mobile<input value={newCust.mobile} onChange={e => setNewCust({ ...newCust, mobile: e.target.value })} /></label>
            <label className="f">PAN<input value={newCust.pan} onChange={e => setNewCust({ ...newCust, pan: e.target.value.toUpperCase() })} maxLength={10} placeholder="ABCDE1234F" /></label>
            <label className="f">Email<input type="email" value={newCust.email} onChange={e => setNewCust({ ...newCust, email: e.target.value })} /></label>
            <div className="wide"><button className="btn ghost small" onClick={() => setNewCust(null)}>Search existing borrowers instead</button></div>
          </div>
        ) : (
          <>
            <div className="row">
              <input placeholder="Search by name, mobile or PAN" value={custQ} onChange={e => setCustQ(e.target.value)} style={{ width: 320 }} aria-label="Search borrowers" />
              <button className="btn ghost" onClick={() => setNewCust({ name: custQ, mobile: '', pan: '', email: '' })}>Add new borrower</button>
            </div>
            {custs.length > 0 && <div className="table-wrap" style={{ marginTop: '.75rem' }}><table><tbody>
              {custs.map(c => <tr key={c.id} className="click" onClick={() => setCust(c)}><td>{c.name}</td><td>{c.mobile}</td><td>{c.pan}</td><td className="n"><button className="btn ghost small">Choose</button></td></tr>)}
            </tbody></table></div>}
          </>
        )}
      </section>

      <form className="panel" onSubmit={preview}>
        <h2>Loan terms</h2>
        <div className="form">
          <label className="f">Product<select value={f.product_id} onChange={e => { const p = products.find(x => String(x.id) === e.target.value); setPrev(null); setF({ ...f, product_id: e.target.value, annual_rate: p?.default_rate ?? '' }) }}>
            {products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.code})</option>)}
          </select></label>
          <label className="f">Amount (₹)<input type="number" step="0.01" value={f.principal} onChange={set('principal')} required min={product?.min_amount} max={product?.max_amount} /></label>
          <label className="f">Rate (% a year)<input type="number" step="0.01" value={f.annual_rate} onChange={set('annual_rate')} required /></label>
          <label className="f">Tenure (months)<input type="number" value={f.tenure_months} onChange={set('tenure_months')} required min={product?.min_tenure} max={product?.max_tenure} /></label>
          <label className="f">Disbursal date<input type="date" value={f.disbursal_date} onChange={set('disbursal_date')} required /></label>
          <label className="f">First EMI date<input type="date" value={f.first_due_date} onChange={set('first_due_date')} /></label>
        </div>
        {product && <p className="small muted" style={{ marginTop: '.75rem' }}>
          {product.interest_method === 'FLAT' ? 'Flat rate' : 'Reducing balance'}, {money(product.min_amount)} to {money(product.max_amount)}, {product.min_tenure} to {product.max_tenure} months.
          Leave the first EMI date empty for one month after disbursal; any other date charges broken-period interest on actual days.
        </p>}
        <div className="row end"><button className="btn ghost">Show schedule</button></div>
      </form>

      {prev && (
        <section className="panel flush">
          <div className="row" style={{ padding: '1rem 1.25rem' }}>
            <div><div className="small muted">EMI</div><strong>{money(prev.rows[Math.min(1, prev.rows.length - 1)].emi)}</strong></div>
            <div style={{ marginLeft: '1.5rem' }}><div className="small muted">Total interest</div><strong>{money(prev.total_interest)}</strong></div>
            <div style={{ marginLeft: '1.5rem' }}><div className="small muted">Total payable</div><strong>{money(prev.total_payable)}</strong></div>
            <div style={{ marginLeft: '1.5rem' }}><div className="small muted">Processing fee</div><strong>{money(prev.processing_fee)}</strong></div>
            <div className="spacer" />
            <button className="btn" onClick={book} disabled={busy}>{busy ? 'Booking…' : 'Book loan'}</button>
          </div>
          <div className="table-wrap"><table>
            <thead><tr><th className="n">EMI</th><th>Due date</th><th className="n">Opening balance</th><th className="n">Principal</th><th className="n">Interest</th><th className="n">Instalment</th><th className="n">Closing balance</th></tr></thead>
            <tbody>{prev.rows.map(r => (
              <tr key={r.installment_no}><td className="n">{r.installment_no}</td><td>{fmtDate(r.due_date)}</td><td className="n">{money(r.opening_balance)}</td><td className="n">{money(r.principal)}</td><td className="n">{money(r.interest)}</td><td className="n">{money(r.emi)}</td><td className="n">{money(r.closing_balance)}</td></tr>
            ))}</tbody>
          </table></div>
        </section>
      )}
    </>
  )
}
