import React, { useEffect, useState } from 'react'
import { api, download, money, fmtDate, today } from '../api'
import { Msg } from '../ui'
import { useUser } from '../main'

const CLEAR_PHRASE = 'DELETE ALL LOAN DATA'

export default function Data() {
  const user = useUser()
  return (
    <>
      <div className="head">
        <div><h1>Data</h1><div className="sub">Export loan data with the columns you choose.</div></div>
      </div>
      <ExportPanel title="Export loan master" kind="loan-master" listKey="loan_master" file="loan_master.csv" />
      <ExportPanel title="Export RPS" kind="rps" listKey="rps" file="rps.csv" />
      {(user.role === 'ADMIN' || user.role === 'OPS') && <GeneratePanel />}
      {user.role === 'ADMIN' && <ClearPanel />}
    </>
  )
}

function ExportPanel({ title, kind, listKey, file }) {
  const [cols, setCols] = useState(null)
  const [picked, setPicked] = useState({})
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api('/export/columns')
      .then(d => { setCols(d[listKey]); setPicked(Object.fromEntries(d[listKey].map(c => [c.key, true]))) })
      .catch(e => setErr(e.message))
  }, [listKey])
  const chosen = cols ? cols.filter(c => picked[c.key]).map(c => c.key) : []
  const go = async () => {
    setBusy(true); setErr('')
    try { await download(`/export/${kind}`, { columns: chosen.join(',') }, file) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <section className="panel">
      <h2>{title}</h2>
      <Msg error={err} />
      {!cols ? <p className="muted">Loading columns…</p> : (
        <>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '.5rem 1.25rem' }}>
            {cols.map(c => (
              <label key={c.key} className="small" style={{ display: 'flex', gap: '.35rem', alignItems: 'center' }}>
                <input type="checkbox" checked={!!picked[c.key]} onChange={e => setPicked({ ...picked, [c.key]: e.target.checked })} />
                {c.label}
              </label>
            ))}
          </div>
          <div className="row" style={{ marginTop: '1rem' }}>
            <button className="btn ghost small" onClick={() => setPicked(Object.fromEntries(cols.map(c => [c.key, true])))}>Select all</button>
            <button className="btn ghost small" onClick={() => setPicked({})}>Clear selection</button>
            <div className="spacer" />
            <button className="btn" disabled={busy || chosen.length === 0} onClick={go}>{busy ? 'Preparing…' : 'Download CSV'}</button>
          </div>
        </>
      )}
    </section>
  )
}

function GeneratePanel() {
  const [replace, setReplace] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const run = async () => {
    if (replace && !window.confirm('Replace the RPS of loans that already have one (including uploaded rows)?')) return
    setBusy(true); setErr(''); setRes(null)
    try { setRes(await api('/rps/generate', { method: 'POST', body: { replace } })) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <section className="panel">
      <h2>Generate RPS from EMI</h2>
      <p className="small">Builds each loan's repayment schedule from the EMI in the loan master, at the IRR. Interest is charged monthly on the balance, principal is the rest of the EMI, and the rounding difference lands in the final due so every month is the same EMI. Loans that already have an RPS are skipped unless you choose to replace them.</p>
      <Msg error={err} />
      <div className="row">
        <label className="small" style={{ display: 'flex', gap: '.35rem', alignItems: 'center' }}>
          <input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)} />
          Replace existing RPS rows
        </label>
        <div className="spacer" />
        <button className="btn" disabled={busy} onClick={run}>{busy ? 'Generating…' : 'Generate RPS'}</button>
      </div>
      {res && (
        <div style={{ marginTop: '1rem' }}>
          <p className="small">{res.loans_generated} loans generated, {res.rows} rows. Skipped (already have RPS): {res.skipped.length}. Errors: {res.errors.length}.</p>
          {res.errors.length > 0 && <div className="table-wrap"><table><thead><tr><th>Loan</th><th>Problem</th></tr></thead><tbody>{res.errors.map((e, i) => <tr key={i}><td>{e.loan_id}</td><td>{e.message}</td></tr>)}</tbody></table></div>}
          {res.warnings.length > 0 && <div className="table-wrap" style={{ marginTop: '.5rem' }}><table><thead><tr><th>Loan</th><th>Check</th></tr></thead><tbody>{res.warnings.map((w, i) => <tr key={i}><td>{w.loan_id}</td><td>{w.message}</td></tr>)}</tbody></table></div>}
        </div>
      )}
    </section>
  )
}

function ClearPanel() {
  const [text, setText] = useState('')
  const [ok, setOk] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const run = async () => {
    if (!window.confirm('Delete every loan, schedule, payment, RPS row and customer? This cannot be undone.')) return
    setBusy(true); setErr(''); setOk('')
    try {
      const r = await api('/admin/clear-loan-data', { method: 'POST', body: { confirm: text } })
      setOk(`Cleared: ${Object.entries(r).map(([k, v]) => `${v} ${k.replace('_', ' ')}`).join(', ')}.`)
      setText('')
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <section className="panel">
      <h2>Clear loan data (testing)</h2>
      <p className="small">Removes all loans, schedules, payments, charges, RPS rows and customers, so the loan master can be loaded again. Users, products and the audit log are kept. Remove this panel once testing is complete.</p>
      <Msg error={err} ok={ok} />
      <div className="row">
        <input placeholder={CLEAR_PHRASE} value={text} onChange={e => setText(e.target.value)} aria-label="Confirmation phrase" style={{ width: 280 }} />
        <div className="spacer" />
        <button className="btn" disabled={text !== CLEAR_PHRASE || busy} onClick={run}>Clear all loan data</button>
      </div>
    </section>
  )
}
