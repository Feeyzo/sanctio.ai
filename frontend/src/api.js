export async function api(path, { method = 'GET', body, headers = {} } = {}) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', ...headers },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (res.status === 401 && path.startsWith('/api/admin')) window.dispatchEvent(new Event('sanctio:unauthorized'))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

export const fmtDate = (s) => (s ? new Date(s + 'Z').toLocaleString() : '')
export const pretty = (s) => (s || '').replaceAll('_', ' ')
