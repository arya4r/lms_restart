import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, money, fmtDate, today } from '../api'
import { Msg } from '../ui'
import { DocSlots, emptyDocs, docsProblem, uploadAll } from '../Documents'

const AMOUNTS = [
  ['vehicle', 'Vehicle value (₹, before GST)'],
  ['insurance', 'Insurance (₹)'],
  ['rto', 'RTO charges (₹)'],
  ['misc', 'Misc expenses (₹)'],
  ['hsrp', 'HSRP number plate (₹)'],
  ['kazam', 'Kazam earthing (₹)'],
  ['scheme', 'Scheme discount / credit note incl. GST (₹)'],
]
const BLANK = { lan: '', customer_name: '', customer_mobile: '', dealer: '', disbursal_date: today(),
  vehicle: '', insurance: '', rto: '', misc: '', hsrp: '', kazam: '', scheme: '' }

function Single() {
  const nav = useNavigate()
  const [f, setF] = useState(BLANK)
  const [prev, setPrev] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [docs, setDocs] = useState(emptyDocs())
  const [booked, setBooked] = useState(null)
  const set = k => e => { setPrev(null); setF({ ...f, [k]: e.target.value }) }
  const body = () => {
    const b = { ...f }
    AMOUNTS.forEach(([k]) => { b[k] = b[k] === '' ? 0 : b[k] })
    return b
  }
  const preview = async e => {
    e.preventDefault(); setErr('')
    try { setPrev(await api('/lease3w/preview', { method: 'POST', body: body() })) } catch (e) { setErr(e.message) }
  }
  const book = async () => {
    const problem = docsProblem(docs)
    if (problem) { setErr(problem); return }
    setBusy('Booking…'); setErr('')
    try {
      const loan = await api('/lease3w/loans', { method: 'POST', body: body() })
      const failed = await uploadAll(loan.id, docs, (i, n) => setBusy(`Uploading document ${i} of ${n}…`))
      if (failed.length) { setBooked({ loan, failed }); return }
      nav(`/loans/${loan.id}`)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  if (booked) return (
    <section className="panel">
      <h2>Loan {booked.loan.loan_number} is booked</h2>
      <p>These documents did not upload. Add them from the loan's Documents tab:</p>
      <ul>{booked.failed.map(x => <li key={x} className="small">{x}</li>)}</ul>
      <div className="row"><button className="btn" onClick={() => nav(`/loans/${booked.loan.id}`)}>Open the loan</button></div>
    </section>
  )
  const d = prev?.deal
  return (
    <>
      <Msg error={err} />
      <form className="panel" onSubmit={preview}>
        <h2>Borrower and vehicle</h2>
        <div className="form">
          <label className="f">Loan ID<input value={f.lan} onChange={set('lan')} required maxLength={40} placeholder="GRFL/MLM/D001" /></label>
          <label className="f">Customer name<input value={f.customer_name} onChange={set('customer_name')} required /></label>
          <label className="f">Customer mobile<input value={f.customer_mobile} onChange={set('customer_mobile')} /></label>
          <label className="f">Dealer<input value={f.dealer} onChange={set('dealer')} /></label>
          <label className="f">Disbursement date<input type="date" value={f.disbursal_date} onChange={set('disbursal_date')} required /></label>
          {AMOUNTS.map(([k, label]) => (
            <label key={k} className="f">{label}<input type="number" step="0.01" min="0" value={f[k]} onChange={set(k)} required={k === 'vehicle'} /></label>
          ))}
        </div>
        <p className="small muted" style={{ marginTop: '.75rem' }}>
          EMI is ₹31.15 per ₹1,000 of loan (rounded up), 36 EMIs including the advance EMI taken on disbursement. Dues fall on the 10th.
        </p>
        <div className="row end"><button className="btn ghost">Show deal and schedule</button></div>
      </form>

      <DocSlots value={docs} onChange={setDocs} />

      {prev && (
        <section className="panel flush">
          <div className="row" style={{ padding: '1rem 1.25rem', flexWrap: 'wrap', gap: '1.5rem' }}>
            <div><div className="small muted">Loan (ORP)</div><strong>{money(d.loan)}</strong></div>
            <div><div className="small muted">GST IC</div><strong>{money(d.gst_ic)}</strong></div>
            <div><div className="small muted">Security deposit</div><strong>{money(d.security_deposit)}</strong></div>
            <div><div className="small muted">Net outflow</div><strong>{money(d.net_outflow)}</strong></div>
            <div><div className="small muted">EMI</div><strong>{money(d.emi)}</strong></div>
            <div><div className="small muted">ROI (a year)</div><strong>{Number(d.roi_annual_pct).toFixed(2)}%</strong></div>
            <div><div className="small muted">Branch</div><strong>{prev.branch}</strong></div>
            <div className="spacer" />
            <button className="btn" onClick={book} disabled={!!busy}>{busy || 'Book loan'}</button>
          </div>
          <div className="table-wrap"><table>
            <thead><tr><th>Head</th><th className="n">Value</th><th className="n">GST</th><th className="n">Total</th><th className="n">IC</th></tr></thead>
            <tbody>{d.lines.map(l => (
              <tr key={l.head}><td>{l.head}</td><td className="n">{money(l.value)}</td><td className="n">{money(l.gst)}</td><td className="n">{money(l.total)}</td><td className="n">{money(l.ic)}</td></tr>
            ))}</tbody>
          </table></div>
          <div className="table-wrap"><table>
            <thead><tr><th>No.</th><th>Type</th><th>Due date</th><th className="n">Days</th><th className="n">Opening</th><th className="n">Interest</th><th className="n">Principal</th><th className="n">Due</th><th className="n">Closing</th></tr></thead>
            <tbody>{prev.rows.map((r, i) => (
              <tr key={i}><td>{r.installment_no ?? ''}</td><td>{r.kind}</td><td>{fmtDate(r.due_date)}</td><td className="n">{r.days ?? ''}</td><td className="n">{money(r.opening_balance)}</td><td className="n">{money(r.interest)}</td><td className="n">{money(r.principal)}</td><td className="n">{money(r.emi)}</td><td className="n">{money(r.closing_balance)}</td></tr>
            ))}</tbody>
          </table></div>
        </section>
      )}
    </>
  )
}

function Bulk() {
  const [file, setFile] = useState(null)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [prog, setProg] = useState(null)
  const check = async () => {
    setErr(''); setBusy('Checking…')
    try {
      const fd = new FormData()
      fd.append('file', file); fd.append('dry_run', 'true')
      setRes(await api('/lease3w/import', { method: 'POST', form: fd }))
    } catch (e) { setErr(e.message) } finally { setBusy('') }
  }
  // the import runs in the background; poll it for imported / pending counts
  const doImport = async () => {
    setErr(''); setBusy('Importing…'); setProg({ done: 0, total: res?.to_book || 0, percent: 0 })
    try {
      const fd = new FormData()
      fd.append('file', file)
      const { job_id } = await api('/lease3w/import-job', { method: 'POST', form: fd })
      for (;;) {
        await new Promise(r => setTimeout(r, 700))
        const j = await api(`/lease3w/jobs/${job_id}`)
        setProg(j)
        if (j.status === 'done') { setRes(j.result); break }
        if (j.status === 'failed') throw new Error(`${j.error}. ${j.done} loans were imported before it stopped; importing the file again books only the rest.`)
      }
    } catch (e) { setErr(e.message) } finally { setBusy('') }
  }
  return (
    <>
      <Msg error={err} />
      <section className="panel">
        <h2>Upload loans</h2>
        <p className="small muted">CSV in the L3 layout (ID, Customer Name, Dealer Name, Customer Mobile, Disbursement Date, Vehicle Value, Insurance, RTO charges, Kazam Earthing, Misc exp., HSRP, Scheme discount (DP), Status). Rows marked Reverted or with no disbursement date are skipped. Loan IDs already in the LMS are skipped and never regenerated.</p>
        <div className="row">
          <input type="file" accept=".csv" onChange={e => { setFile(e.target.files[0] || null); setRes(null); setProg(null) }} aria-label="L3 CSV file" />
          <button className="btn ghost" disabled={!file || !!busy} onClick={check}>Check file</button>
          <button className="btn" disabled={!file || !!busy || !res?.dry_run || res.to_book === 0} onClick={doImport}>Import loans</button>
          {busy && !prog && <span className="muted small">{busy}</span>}
        </div>
        {prog && (busy || prog.status === 'done') && (
          <div style={{ marginTop: '1rem' }}>
            <div className="row" style={{ gap: '1.5rem' }}>
              <div><div className="small muted">Imported</div><strong>{prog.done}</strong></div>
              <div><div className="small muted">Pending</div><strong>{Math.max(0, (prog.total || 0) - (prog.done || 0))}</strong></div>
              <div><div className="small muted">Total</div><strong>{prog.total || 0}</strong></div>
              <div><div className="small muted">Progress</div><strong>{prog.percent || 0}%</strong></div>
            </div>
            <div className="progress" role="progressbar" aria-valuenow={prog.percent || 0} aria-valuemin={0} aria-valuemax={100}>
              <div style={{ width: `${prog.percent || 0}%` }} />
            </div>
          </div>
        )}
      </section>
      {res && (
        <section className="panel">
          <h2>{res.dry_run ? 'Check result (nothing saved)' : 'Import result'}</h2>
          <div className="row" style={{ gap: '1.5rem' }}>
            <div><div className="small muted">{res.dry_run ? 'Ready to book' : 'Imported'}</div><strong>{res.dry_run ? res.to_book : res.imported}</strong></div>
            {!res.dry_run && <div><div className="small muted">Pending</div><strong>{res.pending}</strong></div>}
            <div><div className="small muted">Skipped</div><strong>{res.skipped}</strong></div>
            <div><div className="small muted">Errors</div><strong>{res.error_count}</strong></div>
            <div><div className="small muted">Total loan amount</div><strong>{money(res.total_loan_amount)}</strong></div>
          </div>
          {res.errors.length > 0 && <div className="table-wrap" style={{ marginTop: '.75rem' }}><table>
            <thead><tr><th className="n">Line</th><th>Loan ID</th><th>Problem</th></tr></thead>
            <tbody>{res.errors.map((e, i) => <tr key={i}><td className="n">{e.line}</td><td>{e.loan_id}</td><td>{e.error}</td></tr>)}</tbody>
          </table></div>}
        </section>
      )}
    </>
  )
}

export default function Lease3W() {
  const [tab, setTab] = useState('single')
  return (
    <>
      <div className="head"><div><h1>3-wheeler lease</h1><div className="sub">Book one L3 loan, or create many from a file. Same calculation as the L3 RPS workbook.</div></div></div>
      <div className="row" style={{ marginBottom: '1rem' }}>
        <button className={tab === 'single' ? 'btn' : 'btn ghost'} onClick={() => setTab('single')}>Book one loan</button>
        <button className={tab === 'bulk' ? 'btn' : 'btn ghost'} onClick={() => setTab('bulk')}>Upload a file</button>
      </div>
      {tab === 'single' ? <Single /> : <Bulk />}
    </>
  )
}
