const TOKEN_KEY = 'lms_token'

export const auth = {
  get token() { try { return localStorage.getItem(TOKEN_KEY) } catch { return null } },
  set(t) { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) } catch {} },
}

export async function api(path, { method = 'GET', body, params, form } = {}) {
  const url = new URL('/api' + path, window.location.origin)
  if (params) Object.entries(params).forEach(([k, v]) => v !== '' && v != null && url.searchParams.set(k, v))
  const headers = {}
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const res = await fetch(url, { method, headers, body: payload })
  if (res.status === 401 && path !== '/auth/login') {
    auth.set(null)
    window.location.href = '/login'
    throw new Error('Session expired, sign in again')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const d = data.detail
    throw new Error(Array.isArray(d) ? d.map(x => `${x.loc?.slice(-1)[0]}: ${x.msg}`).join('; ') : d || `Request failed (${res.status})`)
  }
  return data
}

const inr = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const money = v => (v === null || v === undefined || v === '' ? '—' : '₹' + inr.format(Number(v)))
export const num = v => Number(v || 0)
export const fmtDate = s => s ? new Date(s + 'T00:00:00').toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
export const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)

export async function download(path, params, filename) {
  const url = new URL('/api' + path, window.location.origin)
  Object.entries(params || {}).forEach(([k, v]) => url.searchParams.set(k, v))
  const headers = {}
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  const res = await fetch(url, { headers })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Download failed (${res.status})`)
  }
  const a = document.createElement('a')
  a.href = URL.createObjectURL(await res.blob())
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
