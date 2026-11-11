import React, { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, download, money, num, fmtDate, today } from '../api'
import { Msg, Tag, Modal, Waterfall, FieldGroups, Fields } from '../ui'
import { useUser } from '../main'
import { LoanDocuments } from '../Documents'

const MODES = ['NEFT', 'RTGS', 'IMPS', 'UPI', 'NACH', 'CASH', 'CHEQUE', 'OTHER']

// Tabs under the loan terms. group:<name> shows one loan master group from loan.details_groups.
const SECTIONS = [
  ['position', 'Loan position'],
  ['group:Loan', 'Loan terms'],
  ['group:Lead details', 'Lead details'],
  ['group:Co-applicant', 'Co-applicant'],
  ['group:Other loan master fields', 'Other fields'],
  ['documents', 'Documents'],
]

function PositionTable({ loanId, excess }) {
  const [pos, setPos] = useState(null)
  const [err, setErr] = useState('')
  const [asOf, setAsOf] = useState('')
  const load = (date = '') => api(`/loans/${loanId}/position`, { params: { as_of: date } }).then(setPos).catch(e => setErr(e.message))
  useEffect(() => { load() }, [loanId])
  if (err) return <Msg error={err} />
  if (!pos) return <p className="muted">Loading position…</p>
  const row = (label, r) => (
    <tr key={label}>
      <td>{label}</td>
      <td className="n">{r.charged === null ? '—' : money(r.charged)}</td>
      <td className="n">{r.paid === null ? '—' : money(r.paid)}</td>
      <td className="n">{r.waived === null ? '—' : money(r.waived)}</td>
      <td className="n">{r.outstanding === null ? '—' : money(r.outstanding)}</td>
      <td className="n">{r.overdue === null ? '—' : <span className={num(r.overdue) > 0 ? 'bad' : undefined}>{money(r.overdue)}</span>}</td>
    </tr>
  )
  return (
    <>
      <section className="panel flush">
        <div className="table-wrap"><table>
          <thead><tr><th></th><th className="n">Charged</th><th className="n">Paid</th><th className="n">Waived</th><th className="n">Outstanding</th><th className="n">Overdue</th></tr></thead>
          <tbody>
            {row('Principal', pos.principal)}
            {row('Interest', pos.interest)}
            {row('Disbursement charges', pos.disbursement_charges)}
            {row('Late charges', pos.late_charges)}
            {row('Old M2P charges', pos.old_charges)}
          </tbody>
        </table></div>
      </section>
      <section className="panel">
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <label className="f">DPD as of<input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
          <button className="btn ghost" disabled={!asOf} onClick={() => load(asOf)}>Calculate</button>
          <button className="btn ghost" onClick={() => { setAsOf(''); load() }}>Today</button>
        </div>
        <p className="small" style={{ margin: '.75rem 0 0' }}>
          Days past due as of <strong>{fmtDate(pos.as_of)}</strong>: <strong>{pos.dpd}</strong> ({pos.dpd_bucket}). Counted from the earliest due date with anything unpaid.
        </p>
      </section>
      <section className="panel">
        <p className="small muted" style={{ margin: 0 }}>
          Excess held: <strong>{money(pos.excess)}</strong>. Excess comes from payments and will show here once transactions are uploaded.
        </p>
      </section>
    </>
  )
}

function TransactionsTable({ rows }) {
  if (rows.length === 0) return (
    <section className="panel"><p className="muted">No payments yet. Upload transactions on the M2P migration page, under Transactions.</p></section>
  )
  const sum = k => rows.reduce((t, r) => t + Number(r[k] || 0), 0)
  return (
    <section className="panel flush">
      <div className="table-wrap"><table>
        <thead><tr>
          <th>Date</th><th className="n">Amount</th><th className="n">Interest</th><th className="n">Principal</th>
          <th className="n">Charges</th><th className="n">Excess held</th><th>Reference</th>
        </tr></thead>
        <tbody>{rows.map(t => (
          <tr key={t.id}>
            <td>{fmtDate(t.txn_date)}</td><td className="n">{money(t.amount)}</td>
            <td className="n">{money(t.interest_applied)}</td><td className="n">{money(t.principal_applied)}</td>
            <td className="n">{money(t.charges_applied)}</td><td className="n">{money(t.excess_held)}</td>
            <td>{t.reference || '—'}</td>
          </tr>
        ))}</tbody>
        <tfoot><tr>
          <th>Total</th><th className="n">{money(sum('amount'))}</th><th className="n">{money(sum('interest_applied'))}</th>
          <th className="n">{money(sum('principal_applied'))}</th><th className="n">{money(sum('charges_applied'))}</th>
          <th className="n">{money(rows.length ? rows[rows.length - 1].excess_held : 0)}</th><th></th>
        </tr></tfoot>
      </table></div>
      <p className="small muted" style={{ padding: '.75rem 1.25rem 0' }}>
        Each payment goes to interest first, then principal, then charges, for dues already due on the payment date. Money left over is held as excess.
      </p>
    </section>
  )
}

function ForeclosureQuote({ loanId, accountNo }) {
  const [asOf, setAsOf] = useState(today())
  const [q, setQ] = useState(null)
  const [err, setErr] = useState('')
  const calc = () => api(`/loans/${loanId}/foreclosure`, { params: { as_of: asOf } }).then(setQ).catch(e => setErr(e.message))
  const [pdfBusy, setPdfBusy] = useState(false)
  const downloadPdf = async () => {
    setPdfBusy(true); setErr('')
    try { await download(`/loans/${loanId}/foreclosure.pdf`, { as_of: asOf }, `FCL${accountNo}${asOf}.pdf`) } catch (e) { setErr(e.message) } finally { setPdfBusy(false) }
  }
  useEffect(() => { calc() }, [loanId])
  const line = (label, v) => (
    <tr key={label}><td>{label}</td><td className="n">{money(v)}</td></tr>
  )
  return (
    <section className="panel">
      <h2>Foreclosure quote</h2>
      <Msg error={err} />
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="f">Close on<input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
        <button className="btn ghost" disabled={!asOf} onClick={calc}>Calculate</button>
        <button className="btn" disabled={!asOf || pdfBusy} onClick={downloadPdf}>{pdfBusy ? 'Preparing…' : 'Download PDF'}</button>
        <Link className="btn ghost" to={`/loans/${loanId}/quote?as_of=${asOf}`}>Print quote</Link>
      </div>
      {q && (
        <table style={{ marginTop: '1rem' }}>
          <tbody>
            {line('Principal outstanding', q.principal_outstanding)}
            {line(`Interest for the month (${q.interest_note})`, q.interest)}
            {line(`Foreclosure charges (${q.fcl_percent}% of principal)`, q.fcl_charges)}
            {line('GST 18% on foreclosure charges', q.gst)}
            {line('Foreclosure amount', q.fcl_amount)}
            {line('Bounce and late charges (unpaid)', q.bounce_charges)}
            {line('Less excess held', q.excess)}
            {line('Total payable', q.total)}
          </tbody>
        </table>
      )}
    </section>
  )
}

function RpsTable({ loanId }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { api(`/loans/${loanId}/rps`).then(setRows).catch(e => setErr(e.message)) }, [loanId])
  if (err) return <Msg error={err} />
  if (!rows) return <p className="muted">Loading RPS…</p>
  if (rows.length === 0) return (
    <section className="panel"><p className="muted">No RPS for this loan yet. Generate it from the Data page, or upload it on the M2P migration page.</p></section>
  )
  return (
    <section className="panel flush">
      <div className="table-wrap"><table>
        <thead><tr>
          <th className="n">No</th><th>Due date</th><th>EMI paid date</th><th className="n">EMI</th>
          <th className="n">Principal due</th><th className="n">Principal paid</th><th className="n">Interest due</th><th className="n">Interest paid</th>
          <th className="n">Closing balance</th><th className="n">Old M2P charge</th><th className="n">Old M2P paid</th><th className="n">Old M2P waived</th>
          <th className="n">Late charge</th><th className="n">Late charge paid</th>
          <th>Status</th><th>Source</th>
        </tr></thead>
        <tbody>{rows.map(r => (
          <tr key={r.installment_no}>
            <td className="n">{r.installment_no}</td><td>{fmtDate(r.due_date)}</td><td>{r.paid_date ? fmtDate(r.paid_date) : '—'}</td>
            <td className="n">{money(r.emi)}</td><td className="n">{money(r.principal_due)}</td><td className="n">{money(r.principal_paid)}</td>
            <td className="n">{money(r.interest_due)}</td><td className="n">{money(r.interest_paid)}</td><td className="n">{money(r.closing_balance)}</td>
            <td className="n">{money(r.penalty_due)}</td><td className="n">{money(r.penalty_paid)}</td><td className="n">{money(r.penalty_waived)}</td>
            <td className="n">{money(r.late_charge)}</td><td className="n">{money(r.late_charge_paid)}</td>
            <td>{r.paid_date ? 'Paid' : 'Open'}</td><td>{r.source === 'GENERATED' ? 'Generated' : 'Uploaded'}</td>
          </tr>
        ))}</tbody>
      </table></div>
    </section>
  )
}

function pickGroup(groups, name) {
  return Object.fromEntries(Object.entries(groups || {}).filter(([k]) => k === name))
}

export default function LoanDetail() {
  const { id } = useParams()
  const user = useUser()
  const canWrite = user.role === 'ADMIN' || user.role === 'OPS'
  const [loan, setLoan] = useState(null)
  const [reps, setReps] = useState([])
  const [txns, setTxns] = useState([])
  const [charges, setCharges] = useState([])
  const [tab, setTab] = useState('rps')
  const [section, setSection] = useState('position')
  const [modal, setModal] = useState(null)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  const load = useCallback(() => Promise.all([
    api(`/loans/${id}`), api(`/loans/${id}/repayments`), api(`/loans/${id}/charges`), api(`/loans/${id}/transactions`),
  ]).then(([l, r, c, t]) => { setLoan(l); setReps(r); setCharges(c); setTxns(t) }).catch(e => setErr(e.message)), [id])
  useEffect(() => { load() }, [load])

  const done = msg => { setModal(null); setOk(msg); setErr(''); load() }
  if (!loan) return err ? <Msg error={err} /> : <p className="muted">Loading loan…</p>
  const s = loan.summary
  const open = loan.status === 'ACTIVE' || loan.status === 'CLOSED'

  return (
    <>
      <div className="head">
        <div>
          <h1>{loan.loan_number} <Tag>{loan.status.replace('_', ' ')}</Tag> {loan.source === 'M2P' && <Tag>M2P</Tag>}</h1>
          <div className="sub">
            <Link to={`/customers?id=${loan.customer_id}`}>{loan.customer_name}</Link>{loan.customer_mobile && <>, {loan.customer_mobile}</>}, {loan.product_code}, disbursed {fmtDate(loan.disbursal_date)}
          </div>
        </div>
        {canWrite && (
          <div className="row">
            {open && <button className="btn" onClick={() => setModal('pay')}>Post payment</button>}
            {open && <button className="btn ghost" onClick={() => setModal('charge')}>Add charge</button>}
            <Link className="btn ghost" to={`/loans/${id}/soa`}>Print SOA</Link>
          </div>
        )}
      </div>
      <Msg error={err} ok={ok} />

      <div className="tabs" role="tablist">
        {SECTIONS.map(([k, l]) => (
          <button key={k} role="tab" aria-selected={section === k} className={section === k ? 'on' : ''} onClick={() => setSection(k)}>{l}</button>
        ))}
      </div>

      {section === 'position' && <PositionTable loanId={id} excess={s?.excess_amount} />}
      {section === 'documents' && <LoanDocuments loanId={id} canWrite={canWrite} isAdmin={user.role === 'ADMIN'} />}
      {section === 'position' && loan.interest_method !== 'LEASE_3W' && <ForeclosureQuote loanId={id} accountNo={loan.loan_number} />}
      {section.startsWith('group:') && <FieldGroups groups={pickGroup(loan.details_groups, section.slice(6))} />}
      <div className="tabs" role="tablist">
        {[['rps', 'Schedule'], ['payments', `Payments (${txns.length})`], ['charges', `Charges (${charges.length})`]].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {tab === 'rps' && <RpsTable loanId={id} />}
      {tab === 'payments' && <TransactionsTable rows={txns} />}
      {tab === 'charges' && <Charges rows={charges} canWaive={user.role === 'ADMIN'} onWaive={c => setModal({ waive: c })} />}

      {modal === 'pay' && <PaymentModal loan={loan} onClose={() => setModal(null)} onDone={done} />}
      {modal === 'charge' && <ChargeModal loan={loan} onClose={() => setModal(null)} onDone={done} />}
      {modal?.reverse && <ReverseModal rep={modal.reverse} onClose={() => setModal(null)} onDone={done} />}
      {modal?.waive && <WaiveModal charge={modal.waive} onClose={() => setModal(null)} onDone={done} />}
    </>
  )
}

function Payments({ rows, canWrite, onReverse }) {
  const [openId, setOpenId] = useState(null)
  if (!rows.length) return <div className="panel empty">No payments yet. Use Post payment to record one.</div>
  return (
    <div className="panel flush"><div className="table-wrap"><table>
      <thead><tr><th>Date</th><th className="n">Amount</th><th>Mode</th><th>Reference</th><th className="n">To interest</th><th className="n">To principal</th><th className="n">To charges</th><th>Status</th><th /></tr></thead>
      <tbody>
        {rows.map(r => (
          <React.Fragment key={r.id}>
            <tr className={r.status === 'REVERSED' ? 'reversed' : ''}>
              <td>{fmtDate(r.payment_date)}</td><td className="n">{money(r.amount)}</td><td>{r.mode}</td><td>{r.reference || '—'}</td>
              {r.historical
                ? <td colSpan={3} className="muted small">Appropriated in M2P before migration</td>
                : <><td className="n">{money(r.interest)}</td><td className="n">{money(r.principal)}</td><td className="n">{money(r.charges)}</td></>}
              <td>{r.status === 'REVERSED' ? <Tag>Reversed</Tag> : r.purpose === 'FORECLOSURE' ? <Tag>Foreclosure</Tag> : r.historical ? <Tag>M2P</Tag> : <Tag>Paid</Tag>}</td>
              <td className="row" style={{ flexWrap: 'nowrap' }}>
                {r.allocations.length > 0 && <button className="btn ghost small" onClick={() => setOpenId(openId === r.id ? null : r.id)} aria-expanded={openId === r.id}>{openId === r.id ? 'Hide split' : 'Show split'}</button>}
                {canWrite && r.status === 'POSTED' && !r.historical && r.purpose !== 'FORECLOSURE' && <button className="btn danger small" onClick={() => onReverse(r)}>Reverse</button>}
              </td>
            </tr>
            {openId === r.id && r.allocations.map((a, i) => (
              <tr key={i} className="sub"><td /><td className="n">{money(a.amount)}</td><td colSpan={7}>{a.target} {a.component.toLowerCase()}{a.from_excess ? `, from excess on ${fmtDate(a.applied_date)}` : ''}</td></tr>
            ))}
            {r.status === 'REVERSED' && <tr className="sub"><td /><td colSpan={8}>Reversed: {r.reversal_reason}</td></tr>}
          </React.Fragment>
        ))}
      </tbody>
    </table></div></div>
  )
}

function Charges({ rows, canWaive, onWaive }) {
  if (!rows.length) return <div className="panel empty">No charges on this loan.</div>
  return (
    <div className="panel flush"><div className="table-wrap"><table>
      <thead><tr><th>Date</th><th>Type</th><th>Description</th><th className="n">Amount</th><th className="n">Paid</th><th className="n">Waived</th><th className="n">Outstanding</th><th /></tr></thead>
      <tbody>
        {rows.map(c => (
          <tr key={c.id}>
            <td>{fmtDate(c.charge_date)}</td><td>{c.charge_type.replace('_', ' ').toLowerCase()}</td><td>{c.description || '—'}</td>
            <td className="n">{money(c.amount)}</td><td className="n">{money(c.paid)}</td><td className="n">{num(c.waived) ? money(c.waived) : '—'}</td>
            <td className="n">{num(c.outstanding) ? money(c.outstanding) : '—'}</td>
            <td>{canWaive && num(c.amount) - num(c.waived) > 0 && <button className="btn ghost small" onClick={() => onWaive(c)}>Waive</button>}</td>
          </tr>
        ))}
      </tbody>
    </table></div></div>
  )
}

function PaymentModal({ loan, onClose, onDone }) {
  const [f, setF] = useState({ amount: num(loan.summary.total_overdue) > 0 ? loan.summary.total_overdue : loan.emi_amount, payment_date: today(), mode: 'NEFT', reference: '' })
  const [prev, setPrev] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!(Number(f.amount) > 0) || !f.payment_date) { setPrev(null); return }
    const t = setTimeout(() => api(`/loans/${loan.id}/repayments/preview`, { method: 'POST', body: { ...f, reference: null } })
      .then(p => { setPrev(p); setErr('') }).catch(e => { setPrev(null); setErr(e.message) }), 300)
    return () => clearTimeout(t)
  }, [f.amount, f.payment_date])
  const submit = async e => {
    e.preventDefault(); setBusy(true)
    try {
      await api(`/loans/${loan.id}/repayments`, { method: 'POST', body: { ...f, reference: f.reference || null } })
      onDone(`Payment of ${money(f.amount)} posted.`)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const set = k => e => setF({ ...f, [k]: e.target.value })
  return (
    <Modal title="Post payment" onClose={onClose}>
      <form onSubmit={submit}>
        <div className="form">
          <label className="f">Amount (₹)<input type="number" step="0.01" min="0.01" value={f.amount} onChange={set('amount')} required autoFocus /></label>
          <label className="f">Received on<input type="date" value={f.payment_date} max={today()} onChange={set('payment_date')} required /></label>
          <label className="f">Mode<select value={f.mode} onChange={set('mode')}>{MODES.map(m => <option key={m}>{m}</option>)}</select></label>
          <label className="f">Reference / UTR<input value={f.reference} onChange={set('reference')} maxLength={64} /></label>
        </div>
        <h3 style={{ marginTop: '1.25rem' }}>How this payment will be applied</h3>
        {prev ? <>
          <Waterfall interest={prev.interest} principal={prev.principal} charges={prev.charges} excess={prev.excess}
            excessLabel={prev.excess_mode === 'HOLD' ? 'Held as excess' : 'Left over'} steps={prev.lines} />
          {num(prev.excess_already_held) > 0 && <p className="small muted">This loan also holds {money(prev.excess_already_held)} of excess, which adjusts automatically on the next due date.</p>}
        </> : <p className="small muted">Enter an amount and date to see the split.</p>}
        <Msg error={err} />
        <div className="row end"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn" disabled={busy || !prev}>Post payment</button></div>
      </form>
    </Modal>
  )
}

function ChargeModal({ loan, onClose, onDone }) {
  const [f, setF] = useState({ charge_type: 'OTHER', amount: '', charge_date: today(), description: '' })
  const [err, setErr] = useState('')
  const set = k => e => setF({ ...f, [k]: e.target.value })
  const submit = async e => {
    e.preventDefault()
    try { await api(`/loans/${loan.id}/charges`, { method: 'POST', body: f }); onDone('Charge added.') } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title="Add charge" onClose={onClose}>
      <form onSubmit={submit}>
        <div className="form">
          <label className="f">Type<select value={f.charge_type} onChange={set('charge_type')}>
            <option value="LATE_FEE">Late payment charge</option><option value="BOUNCE">Bounce charge</option><option value="LEGAL">Legal charge</option><option value="VISIT">Field visit charge</option><option value="OTHER">Other</option>
          </select></label>
          <label className="f">Amount (₹)<input type="number" step="0.01" min="0.01" value={f.amount} onChange={set('amount')} required /></label>
          <label className="f">Charge date<input type="date" value={f.charge_date} onChange={set('charge_date')} required /></label>
          <label className="f wide">Description<input value={f.description} onChange={set('description')} /></label>
        </div>
        <p className="small muted" style={{ marginTop: '1rem' }}>Charges are collected only after all due interest and principal are cleared.</p>
        <Msg error={err} />
        <div className="row end"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn">Add charge</button></div>
      </form>
    </Modal>
  )
}

function ReverseModal({ rep, onClose, onDone }) {
  const [reason, setReason] = useState('')
  const [bounce, setBounce] = useState(true)
  const [err, setErr] = useState('')
  const submit = async e => {
    e.preventDefault()
    try { await api(`/repayments/${rep.id}/reverse`, { method: 'POST', body: { reason, bounce } }); onDone('Payment reversed and the loan re-apportioned.') } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title={`Reverse payment of ${money(rep.amount)}`} onClose={onClose}>
      <form onSubmit={submit}>
        <p className="small">Every later payment on this loan will be re-applied as if this one never came in.</p>
        <label className="f" style={{ marginBottom: '1rem' }}>Reason<input value={reason} onChange={e => setReason(e.target.value)} placeholder="NACH returned, insufficient funds" required minLength={3} autoFocus /></label>
        <label className="row small"><input type="checkbox" checked={bounce} onChange={e => setBounce(e.target.checked)} /> It bounced, add the product's bounce charge</label>
        <Msg error={err} />
        <div className="row end" style={{ marginTop: '1rem' }}><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn danger">Reverse payment</button></div>
      </form>
    </Modal>
  )
}

function WaiveModal({ charge, onClose, onDone }) {
  const [amount, setAmount] = useState(num(charge.amount) - num(charge.waived))
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')
  const submit = async e => {
    e.preventDefault()
    try { await api(`/charges/${charge.id}/waive`, { method: 'POST', body: { amount, reason } }); onDone('Charge waived.') } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title="Waive charge" onClose={onClose}>
      <form onSubmit={submit}>
        <div className="form">
          <label className="f">Amount to waive (₹)<input type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} required /></label>
          <label className="f">Reason<input value={reason} onChange={e => setReason(e.target.value)} required minLength={3} /></label>
        </div>
        <Msg error={err} />
        <div className="row end" style={{ marginTop: '1rem' }}><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn">Waive charge</button></div>
      </form>
    </Modal>
  )
}
