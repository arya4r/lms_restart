import React, { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, money, fmtDate, today } from '../api'
import { Msg } from '../ui'

// Foreclosure quote for one loan, printable: use the browser's Print, then "Save as PDF"
export default function Quote() {
  const { id } = useParams()
  const [sp] = useSearchParams()
  const asOf = sp.get('as_of') || today()
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    Promise.all([api(`/loans/${id}`), api(`/loans/${id}/foreclosure`, { params: { as_of: asOf } })])
      .then(async ([loan, q]) => {
        const cust = await api(`/customers/${loan.customer_id}`)
        setD({ loan, q, cust })
      })
      .catch(e => setErr(e.message))
  }, [id, asOf])
  if (err) return <Msg error={err} />
  if (!d) return <p className="muted">Preparing quote…</p>
  const { loan, q, cust } = d
  const row = (label, v) => (
    <tr key={label}><td>{label}</td><td className="n">{money(v)}</td></tr>
  )
  return (
    <>
      <div className="row no-print" style={{ marginBottom: '1rem' }}>
        <Link to={`/loans/${id}`}>Back to loan</Link>
        <div className="spacer" />
        <button className="btn" onClick={() => window.print()}>Print / Save as PDF</button>
      </div>
      <div className="soa">
        <h1>Foreclosure quote</h1>
        <div className="small">As of {fmtDate(q.as_of)}</div>

        <section className="soa-block">
          <h3>Customer and loan</h3>
          <table className="soa-table"><tbody>
            <tr><th>Customer</th><td>{cust.name}</td><th>Mobile</th><td>{cust.mobile || '—'}</td></tr>
            <tr><th>Loan account</th><td>{loan.loan_number}</td><th>Product</th><td>{loan.product_code}</td></tr>
            <tr><th>Disbursed</th><td>{fmtDate(loan.disbursal_date)}</td><th>EMI</th><td>{money(loan.emi_amount)}</td></tr>
          </tbody></table>
        </section>

        <section className="soa-block">
          <h3>Amount to close the loan</h3>
          <table className="soa-table"><tbody>
            {row('Principal outstanding', q.principal_outstanding)}
            {row(`Interest (${q.interest_note})`, q.interest)}
            {row(`Foreclosure charges (${q.fcl_percent}% of principal)`, q.fcl_charges)}
            {row('GST 18% on foreclosure charges', q.gst)}
            {row('Foreclosure amount', q.fcl_amount)}
            {row('Bounce and late charges (unpaid)', q.bounce_charges)}
            {row('Less excess held', q.excess)}
            {row('Foreclosure fee', q.foreclosure_fee)}
            <tr><th>Total payable</th><th className="n">{money(q.total)}</th></tr>
          </tbody></table>
        </section>
        <p className="small muted" style={{ marginTop: '1rem' }}>This quote is valid for the date shown. Interest is charged for the month as set out above.</p>
      </div>
    </>
  )
}
