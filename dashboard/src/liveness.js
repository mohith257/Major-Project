// Which nodes are actually alive, derived only from what they report.
// Every live agent posts an FL_UPLOAD every FED_INTERVAL (120s) plus its
// detections, so a node silent for LIVE_MS is shown offline -- the
// topology must never draw a dead node as healthy.
export const NODE_IDS = ['device1', 'device2', 'device3', 'device4']
export const LIVE_MS = 5 * 60 * 1000

export function lastSeen(incidents) {
  const seen = {}
  for (const inc of incidents) {
    const ts = inc.timestamp || 0
    if (ts > (seen[inc.device_id] || 0)) seen[inc.device_id] = ts
  }
  return seen
}

export function liveNodes(incidents, now = Date.now()) {
  const seen = lastSeen(incidents)
  return NODE_IDS.filter((id) => now - (seen[id] || 0) < LIVE_MS)
}

export function ago(ts, now = Date.now()) {
  if (!ts) return 'never'
  const s = Math.max(0, Math.round((now - ts) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

// pre-emptive blocks come from peer threat intel, not this node's own detection
export const isIntelBlock = (inc) => inc.action === 'BLOCK' && /peer threat intel/.test(inc.reason || '')
