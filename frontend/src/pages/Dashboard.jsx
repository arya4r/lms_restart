import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, money, num, fmtDate } from '../api'
import { Msg } from '../ui'

const bucketColor = b => b.startsWith('Current') ? 'var(--paid)' : b.startsWith('NPA') ? 'var(--khata)' : 'var(--amber)'

export default function Dashboard() {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { api('/reports/portfolio').then(setD).catch(e => setErr(e.message)) }, [])
  if (err) return <Msg error={err} />
  if (!d) return <p className="muted">Loading portfolio…</p>
  const pos = num(d.principal_outstanding) || 1
  const efficiency = num(d.demand_this_month) ? Math.min(100, (num(d.collections_this_month) / num(d.demand_this_month)) * 100) : null
  return (
    <>
      <div className="head">
        <div>
          <h1>Portfolio</h1>
          <div className="sub">As of {fmtDate(d.as_of)}</div>
        </div>
        <Link to="/loans/new"><button className="btn">Book a loan</button></Link>
      </div>

      <div className="figures">
        <div className="figure"><div className="label">Principal outstanding</div><div className="value">{money(d.principal_outstanding)}</div></div>
        <div className="figure"><div className="label">Active loans</div><div className="value">{d.active_loans}</div></div>
        <div className="figure"><div className="label">Loans imported</div><div className="value">{d.loans_imported}</div></div>
        <div className="figure"><div className="label">RPS rows imported</div><div className="value">{d.rps_rows_imported}</div></div>
        <div className="figure"><div className="label">Last transaction uploaded</div><div className="value">{d.last_transaction_upload ? fmtDate(d.last_transaction_upload) : '—'}</div>{d.last_transaction_payment_date && <div className="small muted">latest payment dated {fmtDate(d.last_transaction_payment_date)}</div>}</div>
        <div className="figure"><div className="label">Overdue (all dues)</div><div className="value bad">{money(d.total_overdue)}</div></div>
        <div className="figure"><div className="label">Collected this month</div><div className="value good">{money(d.collections_this_month)}</div></div>
        <div className="figure"><div className="label">Collection vs demand</div><div className="value">{efficiency === null ? '—' : efficiency.toFixed(1) + '%'}</div></div>
      </div>

      <div className="grid2">
        <section className="panel flush">
          <h2>Ageing by days past due</h2>
          <div className="table-wrap"><table>
            <thead><tr><th>Bucket</th><th className="n">Loans</th><th className="n">Principal o/s</th><th>Share</th></tr></thead>
            <tbody>
              {d.dpd_buckets.map(b => (
                <tr key={b.bucket}>
                  <td>{b.bucket}</td><td className="n">{b.count}</td><td className="n">{money(b.pos)}</td>
                  <td><div className="bucketbar"><div style={{ width: `${(num(b.pos) / pos) * 100}%`, background: bucketColor(b.bucket) }} /></div></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </section>
        <section className="panel flush">
          <h2>Book by origin</h2>
          <div className="table-wrap"><table>
            <thead><tr><th>Origin</th><th className="n">Active loans</th><th className="n">Principal o/s</th></tr></thead>
            <tbody>
              {d.by_source.length === 0 && <tr><td colSpan={3} className="muted">No active loans yet. Import the M2P book or book a new loan.</td></tr>}
              {d.by_source.map(s => (
                <tr key={s.source}><td>{s.source === 'M2P' ? 'Migrated from M2P' : 'Booked here'}</td><td className="n">{s.count}</td><td className="n">{money(s.pos)}</td></tr>
              ))}
            </tbody>
          </table></div>
          <div style={{ padding: '0 1.25rem 1rem' }} className="small muted">
            Loan status: {Object.entries(d.status_count).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(', ') || 'none'}
          </div>
        </section>
      </div>
    </>
  )
}
