// Cloudflare Pages Function — same-origin read-only proxy for the dashboard.
//
// The browser calls /api/rounds and /api/incidents. This function forwards
// them to the real AWS API Gateway, injecting the x-api-key header from a
// SERVER-SIDE env var so the key never ships in the JS bundle.
//
// Set in Cloudflare Pages -> Settings -> Environment variables (NOT prefixed
// with VITE_, so Vite never inlines them):
//   API_BASE_URL  e.g. https://xxxx.execute-api.ap-south-1.amazonaws.com/prod
//   API_KEY       the API Gateway key
//
// Only GET on the two read endpoints is allowed; the proxy can never be used
// to POST, even if the underlying key would permit it.
const ALLOWED = new Set(['rounds', 'incidents'])

export async function onRequest(context) {
  const { request, env, params } = context

  if (request.method !== 'GET') {
    return json({ error: 'method not allowed' }, 405)
  }

  const segs = Array.isArray(params.path) ? params.path : [params.path].filter(Boolean)
  const endpoint = segs[0] || ''
  if (!ALLOWED.has(endpoint) || segs.length !== 1) {
    return json({ error: 'not found' }, 404)
  }

  if (!env.API_BASE_URL) {
    return json({ error: 'API_BASE_URL not configured' }, 500)
  }

  const incoming = new URL(request.url)
  const target = new URL(env.API_BASE_URL.replace(/\/$/, '') + '/' + endpoint)
  target.search = incoming.search

  let upstream
  try {
    upstream = await fetch(target.toString(), {
      method: 'GET',
      headers: { 'x-api-key': env.API_KEY || '' },
    })
  } catch (e) {
    return json({ error: 'upstream fetch failed', detail: String(e) }, 502)
  }

  const body = await upstream.text()
  return new Response(body, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') || 'application/json',
      'cache-control': 'no-store',
    },
  })
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  })
}
