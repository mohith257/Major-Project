import AttentionBar from './AttentionBar.jsx'

function formatTime(ts) {
  if (!ts) return '-'
  return new Date(ts).toLocaleTimeString()
}

export default function IncidentFeed({ incidents }) {
  return (
    <div className="card">
      <h2>Incident Feed</h2>
      <p className="card-subtitle">
        Autonomous decisions logged by each device&apos;s DefenseActuator, with
        an attention-rollout explanation of which input features drove the
        call (heuristic attribution, not a causal proof -- hover a bar).
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Device</th>
              <th>Action</th>
              <th>Confidence</th>
              <th>Source IP</th>
              <th>Why</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {incidents.map((inc, i) => (
              <tr
                key={i}
                className={
                  inc.action === 'BLOCK' ? 'row-block' : inc.action === 'ALERT' ? 'row-alert' : ''
                }
              >
                <td>{formatTime(inc.timestamp)}</td>
                <td>{inc.device_id}</td>
                <td>
                  <span className={`badge badge-${(inc.action || '').toLowerCase()}`}>
                    {inc.action}
                  </span>
                </td>
                <td>{inc.confidence != null ? `${(inc.confidence * 100).toFixed(0)}%` : '-'}</td>
                <td>{inc.source_ip || '-'}</td>
                <td><AttentionBar attention={inc.attention} /></td>
                <td>{inc.reason}</td>
              </tr>
            ))}
            {incidents.length === 0 && (
              <tr>
                <td colSpan="7" className="empty">No incidents yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
