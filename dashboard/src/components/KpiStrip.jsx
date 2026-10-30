// KPI strip. Every number here is derived from REAL data (the /incidents and
// /rounds feeds) -- no invented counters.
import { NODE_IDS, liveNodes, ago, isIntelBlock } from '../liveness.js'

export default function KpiStrip({ rounds = [], incidents = [] }) {
  const latest = rounds[rounds.length - 1]
  const blocks = incidents.filter((i) => i.action === 'BLOCK')
  const detected = new Set(blocks.filter((i) => !isIntelBlock(i)).map((i) => i.source_ip).filter(Boolean))
  const viaIntel = new Set(blocks.filter(isIntelBlock).map((i) => i.source_ip).filter(Boolean))
  const live = liveNodes(incidents)

  const KPIS = [
    { n: `${live.length}/${NODE_IDS.length}`, label: 'Nodes live (5 min)', cls: live.length < NODE_IDS.length ? 'kpi-warn' : 'kpi-accent' },
    { n: latest ? latest.round : '—', label: latest ? `FL round · closed ${ago(latest.completed_at * 1000)}` : 'FL round', cls: 'kpi-accent2' },
    { n: latest ? `${latest.participants.length}/${NODE_IDS.length}` : '—', label: 'Nodes in last round', cls: '' },
    { n: latest ? (latest.avg_val_accuracy * 100).toFixed(1) + '%' : '—', label: 'Local val acc (avg)', cls: '' },
    { n: detected.size, label: 'Sources blocked (own detection)', cls: 'kpi-danger' },
    { n: viaIntel.size, label: 'Pre-blocked via peer intel', cls: 'kpi-warn' },
  ]

  return (
    <div className="soc-kpis">
      {KPIS.map((k) => (
        <div className={`soc-kpi ${k.cls}`} key={k.label}>
          <div className="soc-kpi-n">{k.n}</div>
          <div className="soc-kpi-l">{k.label}</div>
        </div>
      ))}
    </div>
  )
}
