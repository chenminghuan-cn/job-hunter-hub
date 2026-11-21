const BASE = ''

export async function api(path, { method = 'GET', body, params } = {}) {
  let url = BASE + path
  if (params) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
    ).toString()
    if (qs) url += (url.includes('?') ? '&' : '?') + qs
  }
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    window.location.reload()  // 会话过期：回登录页
  }
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || res.statusText
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return data
}

export const get = (path, params) => api(path, { params })
export const post = (path, body) => api(path, { method: 'POST', body })
export const patch = (path, body) => api(path, { method: 'PATCH', body })
export const del = (path) => api(path, { method: 'DELETE' })
