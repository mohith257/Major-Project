// Live network topology: the 4 edge nodes around the FedAvg core. Every
// state here comes from what the nodes reported:
//   offline  -- nothing from this node for LIVE_MS (no pulses, greyed out)
//   blocking -- this node's OWN detection blocked a source in the last 20s
//   intel    -- this node pre-blocked an IP a PEER detected (federated intel)
//   alert    -- a recent ALERT / INVESTIGATE
//   online   -- reporting, nothing actionable
// Link pulses only animate for live nodes.
import { useEffect, useState } from 'react'
import { NODE_IDS, LIVE_MS, lastSeen, ago, isIntelBlock } from '../liveness.js'

const POS = {
  device1: { x: 120, y: 70 }, device2: { x: 680, y: 70 },
  device3: { x: 120, y: 300 }, device4: { x: 680, y: 300 },
}
const CORE = { x: 400, y: 185 }
const RECENT_MS = 20000

function nodeState(id, incidents, seen, now) {
  if (now - (seen[id] || 0) >= LIVE_MS) return { state: 'offline' }
  let state = 'online'
  let attacker = null
  for (const inc of incidents) {  // newest first
    if (inc.device_id !== id || now - (inc.timestamp || 0) > RECENT_MS) continue
    if (inc.action === 'BLOCK' && !isIntelBlock(inc)) return { state: 'blocking', attacker: inc.source_ip }
    if (isIntelBlock(inc) && state !== 'intel') { state = 'intel'; attacker = inc.source_ip }
    else if ((inc.action === 'ALERT' || inc.action === 'INVESTIGATE') && state === 'online') state = 'alert'
  }
  return { state, attacker }
}

const SUB = { offline: 'OFFLINE', blocking: 'BLOCKING', intel: 'PEER-INTEL BLOCK', alert: 'ALERT', online: 'monitoring' }

export default function Topology({ incidents = [], rounds = [] }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const seen = lastSeen(incidents)
  const states = {}
  NODE_IDS.forEach((id) => { states[id] = nodeState(id, incidents, seen, now) })
  const anyThreat = Object.values(states).some((s) => s.state === 'blocking')
  const latest = rounds[rounds.length - 1]
  const roundAge = latest ? ago(latest.completed_at * 1000, now) : 'never'

  return (
    <div className="card soc-topo">
      <div className="soc-topo-head">
        <h2>Federated Network</h2>
        <span className={`soc-posture ${anyThreat ? 'posture-threat' : 'posture-ok'}`}>
          <span className="soc-dot" /> {anyThreat ? 'THREAT ACTIVE' : 'NO ACTIVE THREAT'}
        </span>
      </div>

      <svg className="soc-svg" viewBox="0 -46 800 462" preserveAspectRatio="xMidYMid meet">
        {NODE_IDS.map((id) => {
          const p = POS[id], s = states[id].state
          return (
            <g key={`link-${id}`}>
              <line x1={CORE.x} y1={CORE.y} x2={p.x} y2={p.y} className="soc-link" />
              {s !== 'offline' && (
                <line x1={CORE.x} y1={CORE.y} x2={p.x} y2={p.y}
                      className={`soc-link-flow ${s === 'blocking' ? 'flow-threat' : s === 'intel' ? 'flow-intel' : ''}`} />
              )}
            </g>
          )
        })}

        <circle cx={CORE.x} cy={CORE.y} r="30" className="soc-core" />
        <circle cx={CORE.x} cy={CORE.y} r="30" className="soc-core-ring" />
        <text x={CORE.x} y={CORE.y - 2} className="soc-core-t1">FedAvg</text>
        <text x={CORE.x} y={CORE.y + 12} className="soc-core-t2">{latest ? `round ${latest.round}` : 'no rounds'}</text>
        <text x={CORE.x} y={CORE.y + 62} className="soc-core-sub">
          {latest ? `${latest.participants.length}/4 nodes · closed ${roundAge}` : ''}
        </text>
        <text x={CORE.x} y={CORE.y + 76} className="soc-core-sub">AWS Lambda · S3 · DynamoDB</text>

        {NODE_IDS.map((id) => {
          const p = POS[id], s = states[id]
          const up = p.y < CORE.y
          return (
            <g key={id} className={`soc-node node-${s.state}`}>
              {s.state === 'blocking' && <circle cx={p.x} cy={p.y} r="40" className="soc-node-alarm" />}
              <rect x={p.x - 64} y={p.y - 26} width="128" height="52" rx="8" className="soc-node-box" />
              <circle cx={p.x - 48} cy={p.y - 6} r="6" className="soc-node-led" />
              <text x={p.x - 34} y={p.y - 6} className="soc-node-label">{id.replace('device', 'device-')}</text>
              <text x={p.x - 34} y={p.y + 8} className="soc-node-sub">{SUB[s.state]}</text>
              <text x={p.x - 34} y={p.y + 20} className="soc-node-seen">seen {ago(seen[id], now)}</text>
              {(s.state === 'blocking' || s.state === 'intel') && s.attacker && (
                <g className={s.state === 'intel' ? 'soc-attacker intel' : 'soc-attacker'}>
                  <line x1={p.x} y1={p.y + (up ? -60 : 60)} x2={p.x} y2={p.y + (up ? -30 : 30)} className="soc-atk-line" />
                  <circle cx={p.x} cy={p.y + (up ? -70 : 70)} r="13" className="soc-atk" />
                  <text x={p.x} y={p.y + (up ? -66 : 74)} className="soc-atk-t">!</text>
                  <text x={p.x} y={p.y + (up ? -88 : 92)} className="soc-atk-ip">{s.attacker}</text>
                </g>
              )}
            </g>
          )
        })}
      </svg>

      <p className="card-subtitle soc-topo-foot">
        Raw traffic never leaves a node; only adapter weights reach the core. Amber = a node
        blocked an IP that a <em>peer</em> detected (shared threat intel), before that IP touched it.
      </p>
    </div>
  )
}
