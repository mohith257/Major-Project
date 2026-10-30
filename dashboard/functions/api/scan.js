// Cloudflare Pages Function — server-side multi-port scanner for the live demo.
//
// A browser (sandboxed, HTTPS) cannot send raw SYNs or sweep ports, so the
// "attack" button calls THIS same-origin endpoint instead. Using Cloudflare's
// TCP socket API it opens real connections to one of the demo nodes across a
// fixed port list — a genuine multi-port scan the node's agent detects on its
// public NIC, firewalls, and shares via peer intel so all four nodes block it.
//
// Safe by construction:
//   - targets ONLY the four hardcoded node IPs (an unknown node = 400),
//   - a fixed port list, no caller-supplied host/port/command,
//   - no shell, no AWS key, nothing to repurpose.
// The scanning IP is Cloudflare's egress, not the visitor's — so the story is
// "press the button, the backend launches a real scan, watch all four nodes
// detect and block it", which is what jurors who can't install a tool will see.
import { connect } from 'cloudflare:sockets'

const NODES = {
  device1: '35.154.172.128',
  device2: '3.109.0.101',
  device3: '65.1.112.185',
  device4: '13.235.241.61',
}
// Common service ports a real scanner sweeps. 25 is omitted (Cloudflare blocks
// outbound SMTP). The fan-out across these ports from one source is exactly the
// signal the node's FlowHistory/agent reads as a scan.
const PORTS = [21, 22, 23, 53, 80, 110, 135, 139, 143, 443, 445,
  1433, 3306, 3389, 5432, 5900, 6379, 8080, 8443, 9200, 27017]

export async function onRequest(context) {
  const { request } = context
  if (request.method !== 'POST' && request.method !== 'GET') {
    return json({ error: 'method not allowed' }, 405)
  }
  const node = new URL(request.url).searchParams.get('node') || 'device1'
  const ip = NODES[node]
  if (!ip) return json({ error: 'unknown node', allowed: Object.keys(NODES) }, 400)

  // Learn our own egress IP so the UI can tell the user exactly which IP the
  // node will block. Same request/PoP as the sockets below, so it matches the
  // source_ip the node records. Best-effort: never fail the scan over this.
  let attacker = null
  try { attacker = (await (await fetch('https://api.ipify.org?format=json')).json()).ip } catch { /* ignore */ }

  const results = await Promise.all(PORTS.map(async (port) => {
    let sock
    try {
      sock = connect({ hostname: ip, port })
      // Awaiting .opened forces the SYN out. A closed port rejects (RST) and a
      // filtered one times out — either way the SYN already reached the node.
      await Promise.race([
        sock.opened,
        new Promise((_, rej) => setTimeout(() => rej(new Error('t')), 1500)),
      ])
      return { port, state: 'open' }
    } catch {
      return { port, state: 'sent' }
    } finally {
      try { await sock.close() } catch { /* already closed */ }
    }
  }))

  return json({
    node, ip, ports_scanned: PORTS.length, results, attacker,
    note: 'Scan sent from the dashboard backend (Cloudflare egress IP ' + (attacker || 'unknown') +
      '). Watch the topology and event stream: this IP is blocked on ' + node +
      ' within seconds and pre-blocked on the other three via peer intel.',
  }, 200)
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store',
      'access-control-allow-origin': '*' },
  })
}
