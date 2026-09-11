// Talks to GET /rounds and GET /incidents (cloud/rounds_lambda,
// cloud/incidents_read_lambda). No write calls here -- the dashboard is
// read-only, devices are the only thing that ever POSTs.
const BASE_URL = import.meta.env.VITE_API_BASE_URL
const API_KEY = import.meta.env.VITE_API_KEY

async function get(path, params = {}) {
  if (!BASE_URL) throw new Error('VITE_API_BASE_URL not configured')
  const url = new URL(BASE_URL.replace(/\/$/, '') + path)
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v))
  const resp = await fetch(url, { headers: { 'x-api-key': API_KEY || '' } })
  if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`)
  return resp.json()
}

export function fetchRounds(limit = 50) {
  return get('/rounds', { limit })
}

export function fetchIncidents(limit = 100) {
  return get('/incidents', { limit })
}
