import React, { useState } from 'react'
import { download, today } from '../api'
import { Msg } from '../ui'

// Dues report: one row per loan, with totals, as an Excel file
export default function Reports() {
  const [asOf, setAsOf] = useState(today())
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true); setErr('')
    try { await download('/reports/dues.xlsx', { as_of: asOf }, `dues_${asOf}.xlsx`) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <div className="head"><div><h1>Reports</h1><div className="sub">Dues for every loan as of a date, in Excel.</div></div></div>
      <section className="panel">
        <p className="small">One row per loan, with account number, customer name and mobile, principal and interest outstanding and overdue, charges due, total overdue and outstanding, DPD, bucket and excess held. A totals row is at the bottom.</p>
        <Msg error={err} />
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <label className="f">As of<input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
          <div className="spacer" />
          <button className="btn" disabled={busy || !asOf} onClick={go}>{busy ? 'Preparing…' : 'Download Excel'}</button>
        </div>
      </section>
    </>
  )
}
