// SOC-style live event stream: real per-flow verdicts from the agents, newest
// first, color-coded by severity, monospace. The pulsing "LIVE" indicator and
// the thin scan-line are animation; the rows are real /incidents data.
import { useState } from 'react'
import { isIntelBlock } from '../liveness.js'

function hhmmss(ts) {
  if (!ts) return '--:--:--'
  const d = new Date(ts)
  return d.toLocaleTimeString('en-GB', { hour12: false })
}

const SEV = {
  BLOCK: 'sev-block',
  ALERT: 'sev-alert',
  MISS: 'sev-block',
  INVESTIGATE: 'sev-alert',
  ESCALATE: 'sev-alert',
  REJECT_GLOBAL: 'sev-alert',
  RETRAIN: 'sev-info',
  SYNC_DOWNLOAD: 'sev-fl',
  FL_UPLOAD: 'sev-fl',
  ROLLBACK: 'sev-info',
  NOOP: 'sev-ok',
}

export default function LiveStream({ incidents = [], connected }) {
  const [q, setQ] = useState('')
  const query = q.trim().toLowerCase()
  // Filter across IP, device, action and reason so you can type an IP (or part of
  // one) and pull every event for it out of the live noise — e.g. paste the
  // attacker IP from the scan panel and show only its block across the fleet.
  const matched = query
    ? incidents.filter((i) =>
        `${i.source_ip || ''} ${i.device_id || ''} ${i.action || ''} ${i.reason || ''}`
          .toLowerCase()
          .includes(query))
    : incidents
  const rows = matched.slice(0, 40)
  return (
    <div className="card soc-stream">
      <div className="soc-stream-head">
        <h2>Live Event Stream</h2>
        <span className="soc-live"><span className="soc-dot" /> {connected ? 'LIVE' : 'DEMO'}</span>
      </div>
      <input
        className="soc-stream-search mono"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="search IP / device / action…"
      />
      {query && (
        <div className="soc-stream-count">
          {matched.length} match{matched.length === 1 ? '' : 'es'} for “{q.trim()}”
          <button className="soc-stream-clear" onClick={() => setQ('')}>clear</button>
        </div>
      )}
      <div className="soc-stream-body">
        {rows.length === 0 && <div className="soc-stream-empty">{query ? 'no matching events' : 'awaiting traffic…'}</div>}
        {rows.map((inc, i) => {
          const sev = isIntelBlock(inc) ? 'sev-intel' : SEV[inc.action] || 'sev-info'
          return (
            <div className={`soc-evt ${sev}`} key={i}>
              <span className="soc-evt-time">{hhmmss(inc.timestamp)}</span>
              <span className="soc-evt-dev">{inc.device_id}</span>
              <span className={`soc-evt-act ${sev}`}>{inc.action}</span>
              <span className="soc-evt-src">{inc.source_ip || '—'}</span>
              <span className="soc-evt-conf">
                {inc.confidence != null ? `${(inc.confidence * 100).toFixed(0)}%` : ''}
              </span>
              <span className="soc-evt-why">{inc.reason}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
