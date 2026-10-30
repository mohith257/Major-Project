// Returns the visitor's real public IP, which Cloudflare provides as
// CF-Connecting-IP on every request. Used by the sandbox attack button to
// show the judge "that's you" before their browser hits a node from this IP.
// No secrets, no upstream call.
export function onRequest(context) {
  const h = context.request.headers
  const ip =
    h.get('CF-Connecting-IP') ||
    (h.get('X-Forwarded-For') || '').split(',')[0].trim() ||
    ''
  return new Response(JSON.stringify({ ip }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  })
}
