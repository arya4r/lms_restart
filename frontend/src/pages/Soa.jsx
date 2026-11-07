import React, { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, money, fmtDate } from '../api'
import { Msg } from '../ui'

// Statement of account for one loan: printable from the browser
export default function Soa() {
  const { id } = useParams()
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    Promise.all([api(`/loans/${id}`), api(`/loans/${id}/position`), api(`/loans/${id}/rps`), api(`/loans/${id}/transactions`)])
      .then(async ([loan, pos, rps, txns]) => {
        const cust = await api(`/customers/${loan.customer_id}`)
        setD({ loan, pos, rps, txns, cust })
      })
      .catch(e => setErr(e.message))
  }, [id])
  if (err) return <Msg error={err} />
  if (!d) return <p className="muted">Preparing statement…</p>
  const { loan, pos, rps, txns, cust } = d
  return (
    <>
      <div className="row no-print" style={{ marginBottom: '1rem' }}>
        <Link to={`/loans/${id}`}>Back to loan</Link>
        <div className="spacer" />
        <button className="btn" onClick={() => window.print()}>Print</button>
      </div>
      <div className="soa">
        <h1>Statement of account</h1>
        <div className="small">As of {fmtDate(pos.as_of)}</div>

        <section className="soa-block">
          <h3>Customer</h3>
          <div>{cust.name}</div>
          <div>{cust.address || '—'}</div>
          <div>Mobile {cust.mobile || '—'}{cust.pan ? `, PAN ${cust.pan}` : ''}</div>
        </section>

        <section className="soa-block">
          <h3>Loan</h3>
          <table className="soa-table"><tbody>
            <tr><th>Loan account</th><td>{loan.loan_number}</td><th>Product</th><td>{loan.product_code}</td></tr>
            <tr><th>Loan amount</th><td>{money(loan.loan_amount)}</td><th>Principal</th><td>{money(loan.principal)}</td></tr>
            <tr><th>Rate (IRR)</th><td>{Number(loan.annual_rate)}%</td><th>Tenure</th><td>{loan.tenure_months} months</td></tr>
            <tr><th>Disbursed</th><td>{fmtDate(loan.disbursal_date)}</td><th>EMI</th><td>{money(loan.emi_amount)}</td></tr>
            <tr><th>First EMI</th><td>{fmtDate(loan.first_due_date)}</td><th>Last EMI</th><td>{fmtDate(loan.last_due_date)}</td></tr>
          </tbody></table>
        </section>

        <section className="soa-block">
          <h3>Position</h3>
          <table className="soa-table">
            <thead><tr><th></th><th>Charged</th><th>Paid</th><th>Waived</th><th>Outstanding</th><th>Overdue</th></tr></thead>
            <tbody>
              {[['Principal', pos.principal], ['Interest', pos.interest], ['Late charges', pos.late_charges], ['Old M2P charges', pos.old_charges]].map(([label, r]) => (
                <tr key={label}><td>{label}</td><td>{money(r.charged)}</td><td>{money(r.paid)}</td><td>{money(r.waived)}</td><td>{money(r.outstanding)}</td><td>{money(r.overdue)}</td></tr>
              ))}
              <tr><td>Disbursement charges</td><td>{money(pos.disbursement_charges.charged)}</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>
            </tbody>
          </table>
          <div className="small" style={{ marginTop: '.5rem' }}>Days past due: {pos.dpd} ({pos.dpd_bucket}). Excess held: {money(pos.excess)}.</div>
        </section>

        <section className="soa-block">
          <h3>Repayment schedule</h3>
          <table className="soa-table">
            <thead><tr><th>No</th><th>Due date</th><th>Paid on</th><th>EMI</th><th>Principal</th><th>Interest</th><th>Penalty</th><th>Closing balance</th></tr></thead>
            <tbody>{rps.map(r => (
              <tr key={r.installment_no}><td>{r.installment_no}</td><td>{fmtDate(r.due_date)}</td><td>{r.paid_date ? fmtDate(r.paid_date) : '—'}</td>
                <td>{money(r.emi)}</td><td>{money(r.principal_due)}</td><td>{money(r.interest_due)}</td><td>{money(r.penalty_due)}</td><td>{money(r.closing_balance)}</td></tr>
            ))}</tbody>
          </table>
        </section>

        <section className="soa-block">
          <h3>Payments received</h3>
          {txns.length === 0 ? <div className="muted">No payments received.</div> : (
            <table className="soa-table">
              <thead><tr><th>Date</th><th>Amount</th><th>Mode</th><th>Reference</th></tr></thead>
              <tbody>{txns.map(t => <tr key={t.id}><td>{fmtDate(t.txn_date)}</td><td>{money(t.amount)}</td><td>{t.mode || '—'}</td><td>{t.reference || '—'}</td></tr>)}</tbody>
            </table>
          )}
        </section>
      </div>
    </>
  )
}
