// Top command bar: product identity, live clock, connection + threat posture.
// The clock is the cheap honest "this is live right now" signal.
import { useEffect, useState } from 'react'
import { isIntelBlock } from '../liveness.js'

export default function CommandBar({ rounds = [], incidents = [], connected, error }) {
  const [clock, setClock] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setClock(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  const latest = rounds[rounds.length - 1]
  const now = Date.now()
  const activeThreat = incidents.some(
    (i) => i.action === 'BLOCK' && !isIntelBlock(i) && now - (i.timestamp || 0) < 20000
  )

  return (
    <header className="soc-bar">
      <div className="soc-brand">
        <span className="soc-mark" />
        <div>
          <h1>AGENTIC FEDGRID</h1>
          <p>Federated Network Intrusion Detection · autonomous response · read-only observer</p>
        </div>
      </div>
      <div className="soc-bar-right">
        <span className={`soc-chip ${activeThreat ? 'chip-threat' : 'chip-ok'}`}>
          <span className="soc-dot" /> {activeThreat ? 'THREAT DETECTED' : 'DEFENSE NOMINAL'}
        </span>
        <span className={`soc-chip ${connected ? 'chip-live' : 'chip-demo'}`}>
          {connected ? 'LIVE · EC2' : 'BACKEND UNREACHABLE'}
        </span>
        <span className="soc-chip chip-mono">RND {latest ? latest.round : '—'}</span>
        <span className="soc-chip chip-mono soc-clock">{clock.toLocaleTimeString()}</span>
      </div>
      {error && !connected && (
        <div className="soc-bar-err">backend unreachable — {error}</div>
      )}
    </header>
  )
}
