import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, money, fmtDate } from '../api'
import { Msg, Tag } from '../ui'

const PAGE = 20

export default function Loans() {
  const [sp, setSp] = useSearchParams()
  const q = sp.get('q') || '', status = sp.get('status') || '', source = sp.get('source') || ''
  const offset = Number(sp.get('offset') || 0)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [text, setText] = useState(q)
  const nav = useNavigate()

  useEffect(() => {
    setData(null)
    api('/loans', { params: { q, status, source, limit: PAGE, offset } }).then(setData).catch(e => setErr(e.message))
  }, [q, status, source, offset])

  const set = (k, v) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); if (k !== 'offset') n.delete('offset'); setSp(n) }

  return (
    <>
      <div className="head">
        <div><h1>Loans</h1>{data && <div className="sub">{data.total} loans</div>}</div>
        <Link to="/loans/new"><button className="btn">Book a loan</button></Link>
      </div>
      <form className="row" style={{ marginBottom: '1rem' }} onSubmit={e => { e.preventDefault(); set('q', text) }}>
        <input placeholder="Loan number, name or mobile" value={text} onChange={e => setText(e.target.value)} style={{ width: 280 }} aria-label="Search loans" />
        <select value={status} onChange={e => set('status', e.target.value)} aria-label="Status">
          <option value="">Any status</option><option>ACTIVE</option><option>CLOSED</option><option>FORECLOSED</option><option>WRITTEN_OFF</option>
        </select>
        <select value={source} onChange={e => set('source', e.target.value)} aria-label="Origin">
          <option value="">Any origin</option><option value="M2P">Migrated from M2P</option><option value="KFT">Booked in KFT</option><option value="NATIVE">Booked here</option>
        </select>
        <button className="btn ghost">Search</button>
      </form>
      <Msg error={err} />
      <div className="panel flush"><div className="table-wrap"><table>
        <thead><tr>
          <th>Loan</th><th>Borrower</th><th className="n">Principal</th><th className="n">EMI</th>
          <th className="n">Principal o/s</th><th className="n">Overdue</th><th>DPD</th><th>Next due</th><th>Status</th>
        </tr></thead>
        <tbody>
          {!data && <tr><td colSpan={9} className="muted">Loading…</td></tr>}
          {data?.items.length === 0 && <tr><td colSpan={9} className="empty">No loans match. Clear the filters or book a new loan.</td></tr>}
          {data?.items.map(l => (
            <tr key={l.id} className="click" onClick={() => nav(`/loans/${l.id}`)}>
              <td><Link to={`/loans/${l.id}`} onClick={e => e.stopPropagation()}>{l.loan_number}</Link>{l.source !== 'NATIVE' && <> <Tag>{l.source}</Tag></>}</td>
              <td>{l.customer_name}</td>
              <td className="n">{money(l.principal)}</td>
              <td className="n">{money(l.emi_amount)}</td>
              <td className="n">{money(l.summary.principal_outstanding)}</td>
              <td className="n">{Number(l.summary.total_overdue) > 0 ? money(l.summary.total_overdue) : '—'}</td>
              <td>{l.status === 'ACTIVE' ? <Tag>{l.summary.dpd_bucket}</Tag> : '—'}{l.summary.dpd > 0 && <span className="small muted"> {l.summary.dpd}d</span>}</td>
              <td>{fmtDate(l.summary.next_due_date)}</td>
              <td><Tag>{l.status.replace('_', ' ')}</Tag></td>
            </tr>
          ))}
        </tbody>
      </table></div></div>
      {data && data.total > PAGE && (
        <div className="row end">
          <span className="small muted">{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
          <button className="btn ghost small" disabled={offset === 0} onClick={() => set('offset', Math.max(0, offset - PAGE))}>Previous</button>
          <button className="btn ghost small" disabled={offset + PAGE >= data.total} onClick={() => set('offset', offset + PAGE)}>Next</button>
        </div>
      )}
    </>
  )
}
