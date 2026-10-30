// Talks to GET /rounds and GET /incidents (cloud/rounds_lambda,
// cloud/incidents_read_lambda). Read-only by design -- the dashboard is an
// observer; devices are the only thing that ever POSTs.
//
// Two modes:
//  - Hosted (Cloudflare Pages): no VITE_API_* vars in the build, so we call
//    the same-origin /api/* proxy (functions/api/[[path]].js), which injects
//    the key server-side. The key never reaches the browser.
//  - Local dev: set VITE_API_BASE_URL + VITE_API_KEY in .env.local and we
//    call AWS directly (convenient hot-reload without running the proxy).
const DIRECT_BASE = import.meta.env.VITE_API_BASE_URL
const DIRECT_KEY = import.meta.env.VITE_API_KEY
const USE_DIRECT = Boolean(DIRECT_BASE)

async function get(path, params = {}) {
  let url
  const headers = {}
  if (USE_DIRECT) {
    url = new URL(DIRECT_BASE.replace(/\/$/, '') + path)
    headers['x-api-key'] = DIRECT_KEY || ''
  } else {
    url = new URL('/api' + path, window.location.origin)
  }
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v))
  const resp = await fetch(url, { headers })
  if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`)
  return resp.json()
}

export function fetchRounds(limit = 50) {
  return get('/rounds', { limit })
}

// 300 so a chatty internet-facing node can't push the quiet nodes'
// FL_UPLOAD heartbeats out of the window used for liveness
export function fetchIncidents(limit = 300) {
  return get('/incidents', { limit })
}
