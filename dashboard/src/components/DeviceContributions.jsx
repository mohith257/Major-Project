// Participation matrix: each node's presence across the last N federated
// rounds. A filled cell = the node contributed an update that round; a dashed
// empty cell = it missed (e.g. pulled offline). This replaces a bar chart that
// just showed every node pinned at the fetch limit (all nodes participate every
// round in steady state), which looked frozen. The matrix instead makes a
// dropped node show up as a visible gap -- the pull-a-node demo moment.
import { NODE_IDS } from '../liveness.js'

const WINDOW = 24

export default function DeviceContributions({ rounds }) {
  const recent = rounds.slice(-WINDOW) // ascending, oldest -> newest

  return (
    <div className="card">
      <h2>Device Participation</h2>
      <p className="card-subtitle">
        Each node across the last {recent.length} round{recent.length === 1 ? '' : 's'}
        {' '}(oldest → newest). A gap = that node missed a round; the federation continues without it.
      </p>

      {recent.length === 0 ? (
        <p className="empty">No rounds yet.</p>
      ) : (
        <div className="part-matrix">
          {NODE_IDS.map((id) => {
            const cells = recent.map((r) => (r.participants || []).includes(id))
            const n = cells.filter(Boolean).length
            return (
              <div className="part-row" key={id}>
                <span className="part-label">{id.replace('device', 'device-')}</span>
                <div className="part-cells">
                  {cells.map((on, i) => (
                    <span key={i} className={`part-cell ${on ? 'on' : 'off'}`} />
                  ))}
                </div>
                <span className="part-count">{n}/{recent.length}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
