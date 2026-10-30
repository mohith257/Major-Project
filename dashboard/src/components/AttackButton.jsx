// Sandbox attack button. On click it opens http://<node-ip>:<port> as a
// top-level navigation -- the ONE browser path exempt from mixed-content
// blocking on an HTTPS page -- so the judge's browser really connects to the
// node from their own public IP. The node's model detects that SYN, firewalls
// the IP, and the other three pre-block it via shared threat intel. Nothing is
// faked: the IP that gets blocked is genuinely theirs.
import { useEffect, useState } from 'react'
import { NODE_TARGETS, ATTACK_PORT } from '../targets.js'

export default function AttackButton({ incidents = [] }) {
  const [target, setTarget] = useState(NODE_TARGETS[0].id)
  const [myIp, setMyIp] = useState(null)
  // Persist across refresh: the panel is held in memory, so a page reload used to
  // wipe the "you attacked" state and the status would reset to blank. sessionStorage
  // survives a refresh (same tab) so the block still shows after reloading.
  const [fired, setFired] = useState(() => {
    try { const v = sessionStorage.getItem('atk_fired'); return v ? JSON.parse(v) : null } catch { return null }
  })
  const [scan, setScan] = useState(null) // {label, state:'running'|'done'|'error', ip, ports}

  useEffect(() => {
    let cancelled = false
    // Prefer the IPv4-only endpoint: the attack button hits the node at an IPv4
    // literal, so the node sees the phone's IPv4 egress. On a dual-stack / CLAT
    // mobile network, api.ipify.org (IPv4-only) returns that SAME carrier IPv4,
    // so the "your attack" panel matches. /api/whoami (Cloudflare CF-Connecting-IP)
    // would report IPv6 on most phones and never match -- use it only as fallback.
    async function getIp() {
      try {
        const d = await (await fetch('https://api.ipify.org?format=json')).json()
        if (!cancelled && d.ip) { setMyIp(d.ip); return }
      } catch { /* fall through */ }
      try {
        const d = await (await fetch('/api/whoami')).json()
        if (!cancelled && d.ip) setMyIp(d.ip)
      } catch { /* no IP available */ }
    }
    getIp()
    return () => { cancelled = true }
  }, [])

  const node = NODE_TARGETS.find((n) => n.id === target) || NODE_TARGETS[0]

  // Single-port connect from the viewer's own IP (one SYN). Kept for "that's my
  // IP" runs where the viewer also has a scanner tool on their device.
  function launch() {
    window.open(`http://${node.ip}:${ATTACK_PORT}/`, '_blank', 'noopener,noreferrer')
    const f = { label: node.label, at: Date.now() }
    setFired(f)
    try { sessionStorage.setItem('atk_fired', JSON.stringify(f)) } catch { /* private mode */ }
  }

  // Multi-port scan via the server (Cloudflare Pages Function /api/scan). A browser
  // cannot sweep ports itself, so the backend fires the SYNs. Used for jurors who
  // can't install a tool: one tap = a real scan across all ports = all nodes blue.
  async function launchScan() {
    setScan({ label: node.label, state: 'running' })
    try {
      const r = await fetch(`/api/scan?node=${node.id}`, { method: 'POST' })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'scan failed')
      setScan({ label: node.label, nodeId: node.id, state: 'done', ip: d.ip, ports: d.ports_scanned, at: Date.now() })
    } catch (e) {
      setScan({ label: node.label, state: 'error', msg: String(e.message || e) })
    }
  }

  // Pull THE JUDGE'S attack out of the constant bot-scan noise. Mobile carriers
  // use CGNAT: the IP that egresses to the node (.209) differs per-connection
  // from the one an echo service reports (.170), but both sit in the same /24
  // pool. So match on the carrier /24, not the exact IP. If they tapped Attack we
  // key off that moment (minus 8s slack); if they only scanned the QR and watched
  // (no button press, or a refresh in a fresh tab), fall back to the last 2 minutes
  // so a just-blocked /24 still lights the panel up instead of staying blank.
  const total = NODE_TARGETS.length
  const subnet = myIp && myIp.includes('.') ? myIp.split('.').slice(0, 3).join('.') + '.' : null
  const windowStart = fired ? fired.at - 8000 : Date.now() - 120000
  const mine = subnet
    ? incidents.filter((i) => (i.source_ip || '').startsWith(subnet) && Number(i.timestamp || 0) >= windowStart)
    : []
  // Only a BLOCK writes a firewall rule and is shared as peer intel. An ALERT
  // (score below the node's block threshold) is neither -- don't count it.
  const blockers = [...new Set(
    mine.filter((i) => i.action === 'BLOCK').map((i) => i.device_id)
  )].filter(Boolean).sort()
  const alerts = mine.filter((i) => i.action === 'ALERT')
  const seenIp = mine.length ? (mine.find((i) => i.action === 'BLOCK') || mine[0]).source_ip : null
  const blockedAll = blockers.length >= total

  // The agentic story, read straight from each block's reason: one node DETECTS
  // you first-hand ("threshold policy: block"); the others never saw your packet
  // but block you anyway on its shared intel ("pre-emptive block from peer ...").
  const roleByNode = {}
  mine.forEach((i) => {
    if (i.action === 'ALERT') {
      if (!roleByNode[i.device_id]) roleByNode[i.device_id] = 'alert' // any block outranks an alert
      return
    }
    if (i.action !== 'BLOCK') return
    const r = (i.reason || '').toLowerCase()
    const role = (r.includes('peer') || r.includes('intel')) ? 'peer' : 'detect'
    if (roleByNode[i.device_id] !== 'detect') roleByNode[i.device_id] = role // detect wins
  })
  const peerCount = Object.values(roleByNode).filter((r) => r === 'peer').length

  // Server-scan attribution: the backend scan egresses from a Cloudflare IPv4 we
  // can't read directly (the echo returns a different IPv6), so instead read the
  // REAL blocked IP from the incident feed — the scanned node's own first-hand
  // BLOCK right after the scan is our scan source. Then match that IP everywhere.
  const scanDetect = scan?.state === 'done'
    ? incidents.find((i) => i.device_id === scan.nodeId && i.action === 'BLOCK' &&
        !/(peer|intel)/i.test(i.reason || '') && Number(i.timestamp || 0) >= scan.at - 3000)
    : null
  const scanIp = scanDetect?.source_ip || null
  const scanMine = scanIp ? incidents.filter((i) => i.source_ip === scanIp && i.action === 'BLOCK') : []
  const scanRole = {}
  scanMine.forEach((i) => {
    const r = (i.reason || '').toLowerCase()
    const role = (r.includes('peer') || r.includes('intel')) ? 'peer' : 'detect'
    if (scanRole[i.device_id] !== 'detect') scanRole[i.device_id] = role
  })
  const scanBlockers = Object.keys(scanRole).length

  return (
    <div className="card atk-panel">
      <div className="atk-head">
        <h2>Sandbox — attack a node</h2>
        <span className="atk-tag">LIVE FIRE</span>
      </div>
      <p className="card-subtitle">
        Press the button: your browser connects to the chosen node from <em>your own</em>{' '}
        public IP. Its model detects you, firewalls your IP, and the other three pre-block it
        via shared threat intel. Watch the Live Event Stream &amp; topology below.
      </p>

      <div className="atk-row">
        <select className="atk-select" value={target} onChange={(e) => setTarget(e.target.value)}>
          {NODE_TARGETS.map((n) => (
            <option key={n.id} value={n.id}>{n.label} · {n.ip}</option>
          ))}
        </select>
        <button className="atk-btn" onClick={launchScan} disabled={scan?.state === 'running'}>
          {scan?.state === 'running' ? 'Scanning all ports…' : `Scan all ports of ${node.label}`}
        </button>
        <button className="atk-btn atk-btn-alt" onClick={launch} title="one connection from your own IP; needs a scanner tool on your device to actually block">
          Single hit from my device
        </button>
      </div>
      {scan && (
        <div className={`atk-scanmsg ${scan.state}`}>
          {scan.state === 'running' && `Launching a real multi-port scan on ${scan.label} from the dashboard backend…`}
          {scan.state === 'error' && `Scan failed: ${scan.msg}`}
          {scan.state === 'done' && (
            <>
              <div>
                Real scan sent to <strong>{scan.label}</strong> across <strong>{scan.ports} ports</strong> from the
                dashboard backend. Attacker IP (Cloudflare egress):{' '}
                <strong className="mono">{scanIp || 'resolving from node…'}</strong>
              </div>
              <div className="atk-scan-verdict mono">
                {scanBlockers
                  ? `BLOCKED on ${scanBlockers}/${total} nodes`
                  : 'waiting for the nodes to block it… (watch the topology & stream)'}
              </div>
              <div className="atk-nodes">
                {NODE_TARGETS.map((n) => (
                  <span key={n.id} className={`atk-node ${scanRole[n.id] ? 'hit ' + scanRole[n.id] : ''}`}>
                    {n.label}
                    {scanRole[n.id] === 'detect' && <em> · detected</em>}
                    {scanRole[n.id] === 'peer' && <em> · peer intel</em>}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      <p className="atk-ip">
        {myIp
          ? <>Your public IP: <strong className="mono">{myIp}</strong></>
          : 'Detecting your public IP…'}
      </p>

      {myIp && (
        <div className={`atk-status ${blockers.length ? (blockedAll ? 'all' : 'some') : 'wait'}`}>
          <div className="atk-status-line">
            <span className="atk-status-ip mono">{seenIp || myIp}</span>
            <span className="atk-status-verdict">
              {blockers.length
                ? `BLOCKED · ${blockers.length}/${total} nodes`
                : alerts.length ? 'ALERT only — not blocked'
                : fired ? 'waiting for block…' : 'not attacked yet'}
            </span>
          </div>
          {seenIp && seenIp !== myIp && (
            <div className="atk-cgnat">your device reports {myIp}; carrier NAT egressed as {seenIp} — same you</div>
          )}
          <div className="atk-nodes">
            {NODE_TARGETS.map((n) => (
              <span key={n.id} className={`atk-node ${roleByNode[n.id] ? 'hit ' + roleByNode[n.id] : ''}`}>
                {n.label}
                {roleByNode[n.id] === 'detect' && <em> · detected</em>}
                {roleByNode[n.id] === 'peer' && <em> · peer intel</em>}
                {roleByNode[n.id] === 'alert' && <em> · alert only</em>}
              </span>
            ))}
          </div>
          {!blockers.length && alerts.length > 0 && (
            <div className="atk-cgnat">
              scored P(attack) = {Number(alerts[0].confidence || 0).toFixed(2)}, below the node's block
              threshold, so it alerted instead of firewalling — and only blocks are shared as peer intel.
              Attack again with more connections (port scan) to cross the threshold.
            </div>
          )}
          {peerCount > 0 && (
            <div className="atk-agentic">
              1 node detected you first-hand; {peerCount} other{peerCount === 1 ? '' : 's'} blocked you
              autonomously on its shared threat intel — never having seen your traffic.
            </div>
          )}
        </div>
      )}

      {fired && (
        <p className="atk-note">
          Fired at <strong>{fired.label}</strong>. The new tab that says “can’t connect” is the
          payoff — you’re being firewalled. Your IP is isolated above; it fills in as each node
          blocks it (the stream below also shows live bot traffic being blocked in the background).
        </p>
      )}
    </div>
  )
}
