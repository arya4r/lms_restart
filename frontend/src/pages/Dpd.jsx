import React, { useState } from 'react'
import { api, money, fmtDate, today } from '../api'
import { Msg } from '../ui'

// DPD calculator: days past due, bucket and overdue amounts for one account, as of a date
export default function Dpd() {
  const [account, setAccount] = useState('')
  const [asOf, setAsOf] = useState(today())
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const calc = async () => {
    setBusy(true); setErr(''); setRes(null)
    try {
      const found = await api('/loans', { params: { q: account.trim(), limit: 20 } })
      const loan = found.items.find(l => l.loan_number === account.trim())
      if (!loan) throw new Error('No loan with this account number')
      const pos = await api(`/loans/${loan.id}/position`, { params: { as_of: asOf } })
      setRes({ loan, pos })
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <div className="head"><div><h1>DPD calculator</h1><div className="sub">Days past due and overdue amounts for an account, as of a date.</div></div></div>
      <section className="panel">
        <Msg error={err} />
        <div className="row" style={{ alignItems: 'flex-end', flexWrap: 'wrap', gap: '.75rem' }}>
          <label className="f">Account number<input value={account} onChange={e => setAccount(e.target.value)} /></label>
          <label className="f">As of<input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
          <div className="spacer" />
          <button className="btn" disabled={busy || !account.trim() || !asOf} onClick={calc}>{busy ? 'Calculating…' : 'Calculate'}</button>
        </div>
        {res && (
          <table style={{ marginTop: '1rem' }}>
            <tbody>
              <tr><td>Customer</td><td className="n">{res.loan.customer_name}</td></tr>
              <tr><td>Days past due as of {fmtDate(res.pos.as_of)}</td><td className="n"><strong>{res.pos.dpd}</strong> ({res.pos.dpd_bucket})</td></tr>
              <tr><td>Oldest unpaid due date</td><td className="n">{fmtDate(res.pos.oldest_unpaid_due)}</td></tr>
              <tr><td>Principal overdue</td><td className="n">{money(res.pos.principal.overdue)}</td></tr>
              <tr><td>Interest overdue</td><td className="n">{money(res.pos.interest.overdue)}</td></tr>
              <tr><td>Charges overdue</td><td className="n">{money(res.pos.late_charges.overdue)}</td></tr>
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
