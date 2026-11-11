import React, { useEffect, useState } from 'react'
import { api, auth, fmtDate } from './api'
import { Msg } from './ui'

const ACCEPT = '.pdf,.jpg,.jpeg,.png,.webp,.heic'
const MAX_MB = 10

export function useDocTypes() {
  const [types, setTypes] = useState([])
  useEffect(() => { api('/documents/types').then(setTypes).catch(() => setTypes([])) }, [])
  return types
}

export const emptyDocs = () => ({ slots: {}, others: [] })

const tooBig = f => f && f.size > MAX_MB * 1024 * 1024

// Document slots on the booking form. Files stay in the browser until the loan is booked.
export function DocSlots({ value, onChange }) {
  const types = useDocTypes().filter(t => t.code !== 'OTHER')
  const setSlot = (code, file) => onChange({ ...value, slots: { ...value.slots, [code]: file || undefined } })
  const setOther = (i, patch) => onChange({ ...value, others: value.others.map((o, j) => j === i ? { ...o, ...patch } : o) })
  const count = Object.values(value.slots).filter(Boolean).length + value.others.filter(o => o.file).length
  return (
    <section className="panel">
      <h2>Documents <span className="small muted">({count} chosen)</span></h2>
      <p className="small muted">PDF or photo, up to {MAX_MB} MB each. They are saved with the loan when you book it. Missing ones can be added later from the loan's Documents tab.</p>
      <div className="doc-grid">
        {types.map(t => {
          const f = value.slots[t.code]
          return (
            <div key={t.code} className={'doc-slot' + (f ? ' has' : '')}>
              <div className="doc-name">{t.label}</div>
              {f ? (
                <div className="row">
                  <span className={'small' + (tooBig(f) ? ' bad' : '')} title={f.name}>{f.name}{tooBig(f) && ' (over 10 MB)'}</span>
                  <button type="button" className="link small" onClick={() => setSlot(t.code, null)}>Remove</button>
                </div>
              ) : (
                <input type="file" accept={ACCEPT} aria-label={t.label} onChange={e => setSlot(t.code, e.target.files[0])} />
              )}
            </div>
          )
        })}
      </div>
      <h3 style={{ marginTop: '1rem' }}>Other documents</h3>
      {value.others.map((o, i) => (
        <div key={i} className="row" style={{ marginTop: '.5rem' }}>
          <input placeholder="Document name" value={o.label} onChange={e => setOther(i, { label: e.target.value })} aria-label="Other document name" style={{ width: 220 }} />
          <input type="file" accept={ACCEPT} aria-label="Other document file" onChange={e => setOther(i, { file: e.target.files[0] || null })} />
          <button type="button" className="link small" onClick={() => onChange({ ...value, others: value.others.filter((_, j) => j !== i) })}>Remove</button>
        </div>
      ))}
      <div className="row" style={{ marginTop: '.5rem' }}>
        <button type="button" className="btn ghost small" onClick={() => onChange({ ...value, others: [...value.others, { label: '', file: null }] })}>Add another document</button>
      </div>
    </section>
  )
}

export function docsProblem(value) {
  const all = [...Object.values(value.slots).filter(Boolean), ...value.others.map(o => o.file).filter(Boolean)]
  const big = all.find(tooBig)
  if (big) return `${big.name} is larger than ${MAX_MB} MB`
  const unnamed = value.others.find(o => o.file && !o.label.trim())
  if (unnamed) return 'Give each other document a name'
  return ''
}

async function uploadOne(loanId, docType, label, file) {
  const fd = new FormData()
  fd.append('doc_type', docType); fd.append('label', label || ''); fd.append('file', file)
  return api(`/loans/${loanId}/documents`, { method: 'POST', form: fd })
}

// Uploads everything chosen on the booking form. Returns the names of files that failed.
export async function uploadAll(loanId, value, onProgress) {
  const jobs = [
    ...Object.entries(value.slots).filter(([, f]) => f).map(([code, f]) => [code, '', f]),
    ...value.others.filter(o => o.file).map(o => ['OTHER', o.label, o.file]),
  ]
  const failed = []
  for (let i = 0; i < jobs.length; i++) {
    const [code, label, f] = jobs[i]
    onProgress?.(i + 1, jobs.length)
    try { await uploadOne(loanId, code, label, f) } catch (e) { failed.push(`${f.name}: ${e.message}`) }
  }
  return failed
}

async function openDoc(id) {
  const res = await fetch(`/api/documents/${id}/file`, { headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {} })
  if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || `Could not open (${res.status})`) }
  const url = URL.createObjectURL(await res.blob())
  window.open(url, '_blank', 'noopener')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

const kb = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`

// Documents tab on the loan page: what's uploaded, what's missing, and upload more.
export function LoanDocuments({ loanId, canWrite, isAdmin }) {
  const types = useDocTypes()
  const [docs, setDocs] = useState(null)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [f, setF] = useState({ doc_type: '', label: '', file: null })
  const [busy, setBusy] = useState(false)
  const load = () => api(`/loans/${loanId}/documents`).then(setDocs).catch(e => setErr(e.message))
  useEffect(() => { load() }, [loanId])

  const upload = async e => {
    e.preventDefault(); setErr(''); setOk('')
    if (!f.file) return setErr('Choose a file')
    if (tooBig(f.file)) return setErr(`${f.file.name} is larger than ${MAX_MB} MB`)
    setBusy(true)
    try { await uploadOne(loanId, f.doc_type, f.label, f.file); setOk(`${f.file.name} uploaded`); setF({ doc_type: '', label: '', file: null }); e.target.reset(); load() }
    catch (e2) { setErr(e2.message) } finally { setBusy(false) }
  }
  const remove = async d => {
    if (!window.confirm(`Delete ${d.file_name}? This can't be undone.`)) return
    try { await api(`/documents/${d.id}`, { method: 'DELETE' }); load() } catch (e) { setErr(e.message) }
  }
  if (!docs) return <section className="panel"><Msg error={err} /><p className="muted">Loading documents…</p></section>
  const have = new Set(docs.map(d => d.doc_type))
  const missing = types.filter(t => t.code !== 'OTHER' && !have.has(t.code))
  return (
    <>
      <Msg error={err} ok={ok} />
      <section className="panel flush">
        {docs.length === 0 ? <p className="muted" style={{ padding: '1rem 1.25rem' }}>No documents uploaded yet.</p> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Document</th><th>File</th><th className="n">Size</th><th>Uploaded</th><th /></tr></thead>
            <tbody>{docs.map(d => (
              <tr key={d.id}>
                <td>{d.doc_label}</td><td>{d.file_name}</td><td className="n">{kb(d.size_bytes)}</td>
                <td>{fmtDate(d.uploaded_at?.slice(0, 10))}{d.uploaded_by && <span className="muted">, {d.uploaded_by}</span>}</td>
                <td className="n">
                  {canWrite && <button className="btn ghost small" onClick={() => openDoc(d.id).catch(e => setErr(e.message))}>Open</button>}
                  {isAdmin && <button className="link small" style={{ marginLeft: '.5rem' }} onClick={() => remove(d)}>Delete</button>}
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {missing.length > 0 && <p className="small muted" style={{ padding: '0 1.25rem 1rem' }}>Not uploaded yet: {missing.map(t => t.label).join(', ')}.</p>}
      </section>
      {canWrite && (
        <form className="panel" onSubmit={upload}>
          <h2>Upload a document</h2>
          <div className="form">
            <label className="f">Document<select value={f.doc_type} onChange={e => setF({ ...f, doc_type: e.target.value })} required>
              <option value="">Choose…</option>
              {types.map(t => <option key={t.code} value={t.code}>{t.label}</option>)}
            </select></label>
            {f.doc_type === 'OTHER' && <label className="f">Document name<input value={f.label} onChange={e => setF({ ...f, label: e.target.value })} required /></label>}
            <label className="f">File<input type="file" accept={ACCEPT} onChange={e => setF({ ...f, file: e.target.files[0] || null })} required /></label>
          </div>
          <div className="row end"><button className="btn" disabled={busy}>{busy ? 'Uploading…' : 'Upload'}</button></div>
        </form>
      )}
    </>
  )
}
