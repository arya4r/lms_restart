import React, { useEffect } from 'react'
import { money, num, fmtDate } from './api'

export function Msg({ error, ok }) {
  if (error) return <div className="msg error" role="alert">{error}</div>
  if (ok) return <div className="msg ok" role="status">{ok}</div>
  return null
}

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const k = e => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <div className="modal-bg" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  )
}

const statusClass = s => {
  const v = (s || '').toLowerCase()
  if (v.startsWith('sma')) return 'sma'
  if (v.startsWith('npa')) return 'npa'
  if (v.startsWith('partly') || v.startsWith('advance')) return 'partly'
  return v.split(' ')[0]
}
const sentence = s => typeof s === 'string' && s.length > 3 && s === s.toUpperCase() && !/[0-9(]/.test(s)
  ? s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, ' ') : s
export const Tag = ({ children }) => <span className={'tag ' + statusClass(children)}>{sentence(children)}</span>

/* How a payment splits: interest, principal, charges, then whatever is left. */
export function Waterfall({ interest, principal, charges, excess, steps, excessLabel = 'Held as excess' }) {
  const parts = [
    ['Interest', num(interest), 'var(--interest)'],
    ['Principal', num(principal), 'var(--principal)'],
    ['Charges', num(charges), 'var(--charge)'],
    [excessLabel, num(excess), 'var(--excess)'],
  ]
  const total = parts.reduce((s, p) => s + p[1], 0) || 1
  return (
    <div className="fall">
      <div className="fall-bar" role="img" aria-label={parts.map(p => `${p[0]} ${money(p[1])}`).join(', ')}>
        {parts.filter(p => p[1] > 0).map((p, i) => (
          <div key={p[0]} style={{ width: `${(p[1] / total) * 100}%`, background: p[2], animationDelay: `${i * 0.12}s` }} />
        ))}
      </div>
      <div className="fall-legend">
        {parts.map(p => (
          <div key={p[0]}>
            <div className="k"><i style={{ background: p[2] }} />{p[0]}</div>
            <div className="v">{money(p[1])}</div>
          </div>
        ))}
      </div>
      {steps?.length > 0 && (
        <div className="fall-steps">
          {steps.map((s, i) => (
            <div key={i}><span>{s.target} {s.component.toLowerCase()}</span><span>{money(s.amount)}</span></div>
          ))}
        </div>
      )}
    </div>
  )
}

// Loan master fields, shown as a grid of labelled values rather than a list.
// Amounts and dates are formatted from the column name; everything else is shown as stored.
const NOT_MONEY = /tenure|age|month|count|days|irr|roi|no_|emis|ems$|percent|pct|%|id$|ref|lan$|number|no$/i
const MONEY_KEY = /amount|charge|fee|emi|principal|interest|income|price|bpi|gst|share|premium|rsa|insurance|duty|excess|balance|total|charges|money|disb/i
const DATE_KEY = /date|dob|repayment|disbursal|approved|created/i

export function fieldValue(key, v) {
  const s = String(v)
  if (DATE_KEY.test(key) && /^\d{4}-\d{2}-\d{2}/.test(s)) return fmtDate(s.slice(0, 10))
  if (MONEY_KEY.test(key) && !NOT_MONEY.test(key) && /^-?\d+(\.\d+)?$/.test(s)) return money(s)
  return s
}

export function Fields({ items }) {
  return (
    <div className="fields">
      {items.map(([label, value]) => (
        <div className="field" key={label}>
          <div className="k">{label}</div>
          <div className="v">{value}</div>
        </div>
      ))}
    </div>
  )
}

// Shows {group name: {column: value}} as a section per group, with the values in a readable grid
export function FieldGroups({ groups }) {
  const names = Object.keys(groups || {})
  if (names.length === 0) return null
  return names.map(name => (
    <section className="panel" key={name}>
      <h2>{name}</h2>
      <Fields items={Object.entries(groups[name]).map(([k, v]) => [k, fieldValue(k, v)])} />
    </section>
  ))
}
