// Real-time rollup of what the devices' EdgeAgents are actually deciding,
// computed client-side from the same /incidents feed IncidentFeed renders
// row-by-row. Exists because a feed that only ever shows BLOCK/ALERT rows
// is indistinguishable from "nothing is watching" when there's no attack
// happening right now -- run_edge_node.py's LIVE_CAPTURE mode now reports a
// sample of benign (NOOP) verdicts too (see its REPORT_CLEAR_EVERY env
// var), specifically so this tile row has something real to show between
// attacks.
function countBy(incidents) {
  const counts = { NOOP: 0, ALERT: 0, BLOCK: 0, RETRAIN: 0, MISS: 0, SYNC_DOWNLOAD: 0 }
  for (const inc of incidents) {
    const action = inc.action || 'NOOP'
    counts[action] = (counts[action] || 0) + 1
  }
  return counts
}

const TILES = [
  { key: 'NOOP', label: 'Clear', cls: 'stat-clear' },
  { key: 'ALERT', label: 'Alert', cls: 'stat-alert' },
  { key: 'BLOCK', label: 'Blocked', cls: 'stat-block' },
  { key: 'RETRAIN', label: 'Retrained', cls: 'stat-retrain' },
  { key: 'MISS', label: 'Missed', cls: 'stat-miss' },
]

export default function LiveAssessment({ incidents, connected }) {
  const counts = countBy(incidents)
  const latest = incidents[0]

  return (
    <div className="card">
      <h2>Live Assessment</h2>
      <p className="card-subtitle">
        {connected
          ? `Real per-flow verdicts from each device's EdgeAgent, over the last ${incidents.length} reported flows.`
          : 'Showing demo data below -- connect the backend (VITE_API_BASE_URL) to see real per-flow verdicts here.'}
      </p>
      <div className="stat-row">
        {TILES.map(({ key, label, cls }) => (
          <div className={`stat-tile ${cls}`} key={key}>
            <span className="stat-n">{counts[key]}</span>
            <span className="stat-label">{label}</span>
          </div>
        ))}
      </div>
      {latest ? (
        <p className="live-latest">
          Latest: <strong>{latest.device_id}</strong> &rarr;{' '}
          <strong>{latest.action}</strong>
          {latest.source_ip ? ` (${latest.source_ip})` : ''}
          {latest.timestamp ? ` @ ${new Date(latest.timestamp).toLocaleTimeString()}` : ''}
        </p>
      ) : (
        <p className="live-latest">No flows reported yet.</p>
      )}
    </div>
  )
}
