import React, { useState } from 'react'
import { api, download, money, today } from '../api'
import { Msg } from '../ui'

// Runs an import as a background job and reports its progress (0-100) while it works
async function runJob(kind, file, dryRun, onProgress) {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('dry_run', dryRun ? 'true' : 'false')
  const { job_id } = await api(`/jobs/import/${kind}`, { method: 'POST', form: fd })
  for (;;) {
    await new Promise(r => setTimeout(r, 2000))
    const j = await api(`/jobs/${job_id}`)
    onProgress(j.percent, j.step)
    if (j.status === 'done') return j.result
    if (j.status === 'failed') throw new Error(j.error)
  }
}

// A collapsible section for long lists of errors and warnings
function Collapsible({ title, count, children }) {
  return (
    <details className="collapse" open={count <= 10}>
      <summary>{title} ({count})</summary>
      {children}
    </details>
  )
}

function TemplateButton({ name }) {
  const [err, setErr] = useState('')
  const ext = name === 'loan_master' ? 'tsv' : 'csv'
  const go = () => download(`/templates/${name}`, {}, `${name}_template.${ext}`).catch(e => setErr(e.message))
  return (
    <>
      <button className="btn ghost" onClick={go}>Download template</button>
      {err && <span className="small" style={{ color: 'var(--khata)' }}>{err}</span>}
    </>
  )
}

const FILES = [
  ['loans', 'Loan master', true, 'Loan Account Number, Customer ID, Customer Name, Mobile, Email, PAN, Address, Product Code, Loan Amount, Principal Amount, ROI, Tenure, Disbursement Date, First EMI Date, Last EMI Date, EMI Amount, Processing Fee, Stamp Duty, Document Charges, Insurance Amount, RSA, Bounce Charges, Loan Status'],
  ['schedule', 'Repayment schedule', true, 'Loan Account Number, Installment No, Due Date, Principal Component, Interest Component, Principal Paid, Interest Paid (paid as on cutoff)'],
  ['receipts', 'Receipts', false, 'Loan Account Number, Receipt Date, Receipt Amount, Payment Mode, UTR'],
  ['charges', 'Charges', false, 'Loan Account Number, Charge Type, Charge Date, Amount, Paid Amount, Waived Amount'],
]

export default function Migration() {
  const [files, setFiles] = useState({})
  const [cutoff, setCutoff] = useState('2026-04-30')
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [eodDate, setEodDate] = useState(today())
  const [eod, setEod] = useState(null)
  const [loanFile, setLoanFile] = useState(null)
  const [loanReport, setLoanReport] = useState(null)
  const [loanBusy, setLoanBusy] = useState(false)
  const [loanPct, setLoanPct] = useState(null)
  const [loanStep, setLoanStep] = useState('')
  const [loanDry, setLoanDry] = useState(true)

  const run = async dryRun => {
    if (!dryRun && !window.confirm('Import these loans into the live book? Loans with errors are skipped.')) return
    setBusy(true); setErr('')
    const fd = new FormData()
    Object.entries(files).forEach(([k, f]) => f && fd.append(k, f))
    fd.append('cutoff', cutoff); fd.append('dry_run', dryRun ? 'true' : 'false')
    try { setReport(await api('/import/m2p', { method: 'POST', form: fd })) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const runLoanMaster = async dryRun => {
    if (!dryRun && !window.confirm('Import these loans without repayment schedules into the live book?')) return
    setLoanBusy(true); setLoanDry(dryRun); setErr(''); setLoanPct(0); setLoanStep('')
    try { setLoanReport(await runJob('loan-master', loanFile, dryRun, (p, st) => { setLoanPct(p); setLoanStep(st || '') })) } catch (e) { setErr(e.message) } finally { setLoanBusy(false); setLoanPct(null) }
  }
  const runEod = async () => {
    setErr('')
    try { setEod(await api('/eod/late-fees', { method: 'POST', params: { as_of: eodDate } })) } catch (e) { setErr(e.message) }
  }
  const ready = files.loans && files.schedule

  return (
    <>
      <div className="head"><div><h1>M2P migration</h1><div className="sub">Bring the M2P book across exactly as it stood on the cutoff date. Payments after the cutoff go through the new waterfall.</div></div></div>
      <Msg error={err} />
      <section className="panel">
        <h2>Export files from M2P</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>File</th><th>Needed</th><th>Columns we read</th><th>Choose CSV</th></tr></thead>
          <tbody>{FILES.map(([k, label, req, cols]) => (
            <tr key={k}>
              <td><strong>{label}</strong></td><td>{req ? 'Required' : 'Optional'}</td><td className="small muted" style={{ maxWidth: 420 }}>{cols}</td>
              <td><input type="file" accept=".csv,text/csv" aria-label={label} onChange={e => { setReport(null); setFiles({ ...files, [k]: e.target.files[0] }) }} /></td>
            </tr>
          ))}</tbody>
        </table></div>
        <p className="small muted" style={{ marginTop: '.75rem' }}>Common M2P header variations (LAN, Loan No, ROI, EMI Due Date, UTR and so on) are recognised. Dates can be DD-MM-YYYY, DD/MM/YYYY or YYYY-MM-DD.</p>
        <div className="row">
          <label className="f">Cutoff date<input type="date" value={cutoff} onChange={e => setCutoff(e.target.value)} /></label>
          <div className="spacer" />
          <button className="btn ghost" disabled={!ready || busy} onClick={() => run(true)}>{busy ? 'Checking…' : 'Check files'}</button>
          <button className="btn" disabled={!ready || busy || !report?.dry_run} onClick={() => run(false)}>Import loans</button>
        </div>
      </section>

      {report && <Report r={report} />}

      <section className="panel">
        <h2>Loan master only</h2>
        <p className="small">Stores customers and loans with their terms, as they are in the file. No cut-off is applied and no repayment schedule is generated. RPS rows are uploaded separately below.</p>
        <div className="row">
          <input type="file" accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values" aria-label="Loan master file" onChange={e => { setLoanReport(null); setLoanFile(e.target.files[0]) }} />
          <div className="spacer" />
          <TemplateButton name="loan_master" />
          <button className="btn ghost" disabled={!loanFile || loanBusy} onClick={() => runLoanMaster(true)}>{loanBusy && loanDry ? `Checking… ${loanPct ?? 0}%${loanStep ? ' · ' + loanStep : ''}` : 'Check file'}</button>
          <button className="btn" disabled={!loanFile || loanBusy || !loanReport?.dry_run} onClick={() => runLoanMaster(false)}>{loanBusy && !loanDry ? `Importing… ${loanPct ?? 0}%` : 'Import loans'}</button>
        </div>
      </section>
      {loanReport && <Report r={loanReport} />}

      <SingleFileImport cutoff={cutoff} title="Schedule" label="Schedule file"
        field="rps" endpoint="/import/rps" template="rps" kind="rps"
        text="Needs the loan master first. Upload the M2P RPS export (account_no, installment, Date, EMI paid Date, closing balance, principal and interest due and paid, penalties, EMI). Each loan's RPS is replaced by the file. Rows for loans not in the loan master are skipped." />

      <SingleFileImport cutoff={cutoff} title="Transactions" label="Transactions file"
        field="transactions" endpoint="/import/transactions" template="transactions" kind="transactions"
        text="Needs the loan master first. Each payment is applied to the loan's schedule in date order: interest, then principal, then charges, for dues already due on the payment date. A charge is added to an instalment still unpaid after the grace period. Money left over is held as excess." />

      <SingleFileImport cutoff={cutoff} title="Charges" label="Charges file"
        field="charges" endpoint="/import/charges"
        text="Needs the loans first. Each charge comes in with the amount paid and waived as on the cutoff." />

      <section className="panel">
        <h2>End of day: late payment charges</h2>
        <p className="small">Levies each product's late fee once on every EMI still unpaid after its grace days. Running it again on the same day adds nothing new. Schedule this daily on the server (see the README).</p>
        <div className="row">
          <label className="f">Run as of<input type="date" value={eodDate} max={today()} onChange={e => setEodDate(e.target.value)} /></label>
          <button className="btn ghost" onClick={runEod} style={{ alignSelf: 'flex-end' }}>Run late fees</button>
          {eod && <span className="small" style={{ alignSelf: 'flex-end' }}>{eod.late_fees_created} late fees added for {eod.as_of}.</span>}
        </div>
      </section>
    </>
  )
}

function SingleFileImport({ cutoff, title, text, field, endpoint, label, template, kind }) {
  const [file, setFile] = useState(null)
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)
  const [pct, setPct] = useState(null)
  const [step, setStep] = useState('')
  const [err, setErr] = useState('')

  const run = async dryRun => {
    if (!dryRun && !window.confirm(`Import this ${title.toLowerCase()} into the live book? Rows with errors are skipped.`)) return
    setBusy(true); setErr(''); setPct(0); setStep('')
    try {
      if (kind) {
        setReport(await runJob(kind, file, dryRun, (p, st) => { setPct(p); setStep(st || '') }))
      } else {
        const fd = new FormData()
        fd.append(field, file); fd.append('cutoff', cutoff); fd.append('dry_run', dryRun ? 'true' : 'false')
        setReport(await api(endpoint, { method: 'POST', form: fd }))
      }
    } catch (e) { setErr(e.message) } finally { setBusy(false); setPct(null) }
  }

  return (
    <>
      <section className="panel">
        <h2>{title}</h2>
        <p className="small">{text}</p>
        <Msg error={err} />
        <div className="row">
          <input type="file" accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values" aria-label={label} onChange={e => { setReport(null); setFile(e.target.files[0]) }} />
          <div className="spacer" />
          {template && <TemplateButton name={template} />}
          <button className="btn ghost" disabled={!file || busy} onClick={() => run(true)}>{busy ? `Checking… ${pct ?? 0}%${step ? ' · ' + step : ''}` : 'Check file'}</button>
          <button className="btn" disabled={!file || busy || !report?.dry_run} onClick={() => run(false)}>Import</button>
        </div>
      </section>
      {report && <Report r={report} />}
    </>
  )
}

function Report({ r }) {
  // transactions results have no warnings or reconciliation; the lists are optional
  const errors = r.errors || []
  const warnings = r.warnings || []
  const reconciliation = r.reconciliation || []
  const clean = errors.length === 0
  if (r.applied !== undefined) {
    return (
      <section className="panel">
        <h2>{r.dry_run ? 'Check result' : 'Import complete'}</h2>
        <Msg ok={r.dry_run ? (clean ? 'Nothing has been saved yet; import when ready.' : null) : `${r.applied} payments applied.`}
          error={r.dry_run && !clean ? `${errors.length} payments have errors and will be skipped.` : null} />
        <div className="figures">
          <div className="figure"><div className="label">Payments in file</div><div className="value">{r.read}</div></div>
          <div className="figure"><div className="label">{r.dry_run ? 'Ready to apply' : 'Applied'}</div><div className="value good">{r.applied}</div></div>
          <div className="figure"><div className="label">Already uploaded</div><div className="value">{r.duplicates}</div></div>
        </div>
        {errors.length > 0 && <Collapsible title="Errors" count={errors.length}>
          <div className="table-wrap"><table><thead><tr><th>File</th><th className="n">Row</th><th>Problem</th></tr></thead>
            <tbody>{errors.slice(0, 200).map((e, i) => <tr key={i}><td>{e.file}</td><td className="n">{e.row}</td><td>{e.message}</td></tr>)}</tbody></table></div>
        </Collapsible>}
      </section>
    )
  }
  return (
    <section className="panel">
      <h2>{r.dry_run ? 'Check result' : 'Import complete'}</h2>
      <Msg ok={r.dry_run ? (clean ? 'All rows passed. Nothing has been saved yet; import when ready.' : null) : `${r.rps_read !== undefined ? r.rps_imported : r.loans_imported} imported.`}
        error={r.dry_run && !clean ? `${errors.length} rows have errors and will be skipped. Fix them in the file and check again.` : null} />
      <div className="figures">
        <div className="figure"><div className="label">{r.rps_read !== undefined ? 'Rows in file' : 'Loans in file'}</div><div className="value">{r.rps_read !== undefined ? r.rps_read : r.loans_read}</div></div>
        <div className="figure"><div className="label">{r.dry_run ? 'Ready to import' : 'Imported'}</div><div className="value good">{r.rps_read !== undefined ? r.rps_imported : r.loans_imported}</div></div>
        <div className="figure"><div className="label">Instalments</div><div className="value">{r.installments}</div></div>
        <div className="figure"><div className="label">Receipts kept as history</div><div className="value">{r.receipts_history}</div></div>
        <div className="figure"><div className="label">Receipts after cutoff</div><div className="value">{r.receipts_post_cutoff}</div></div>
      </div>
      {errors.length > 0 && <Collapsible title="Errors" count={errors.length}>
        <div className="table-wrap"><table><thead><tr><th>File</th><th className="n">Row</th><th>Problem</th></tr></thead>
          <tbody>{errors.slice(0, 200).map((e, i) => <tr key={i}><td>{e.file}</td><td className="n">{e.row}</td><td>{e.message}</td></tr>)}</tbody></table></div>
        {errors.length > 200 && <p className="small muted">Showing the first 200 of {errors.length}.</p>}
      </Collapsible>}
      {warnings.length > 0 && <Collapsible title="Check these" count={warnings.length}>
        <div className="table-wrap"><table><thead><tr><th>Loan</th><th>Note</th></tr></thead>
          <tbody>{warnings.slice(0, 200).map((w, i) => <tr key={i}><td>{w.loan_id}</td><td>{w.message}</td></tr>)}</tbody></table></div>
        {warnings.length > 200 && <p className="small muted">Showing the first 200 of {warnings.length}.</p>}
      </Collapsible>}
      {reconciliation.length > 0 && <>
        <h3 style={{ marginTop: '1rem' }}>Receipts against M2P appropriation, till cutoff</h3>
        <div className="table-wrap"><table><thead><tr><th>Loan</th><th className="n">Receipts</th><th className="n">Appropriated in M2P</th><th className="n">Difference</th></tr></thead>
          <tbody>{reconciliation.map(x => <tr key={x.loan_id}><td>{x.loan_id}</td><td className="n">{money(x.receipts_till_cutoff)}</td><td className="n">{money(x.appropriated_in_m2p)}</td>
            <td className="n" style={{ color: Math.abs(Number(x.difference)) > 1 ? 'var(--khata)' : undefined }}>{Number(x.difference) === 0 ? 'Matches' : money(x.difference)}</td></tr>)}</tbody></table></div>
      </>}
    </section>
  )
}
