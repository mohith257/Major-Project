// Renders one incident's attention-rollout explanation (model/explain.py,
// Objective 5) as a proportional stacked bar -- which of the 4 input
// tokens the classifier attended to most. Heuristic attribution, not a
// causal proof; the tooltip and card subtitle both say so on purpose.
const TOKEN_LABELS = {
  continuous_features: 'Flow stats',
  proto: 'Protocol',
  service: 'Service',
  state: 'Conn. state',
}

const TOKEN_COLORS = {
  continuous_features: '#4fd1c5',
  proto: '#7c9eff',
  service: '#ffb84f',
  state: '#ff6b6b',
}

export default function AttentionBar({ attention }) {
  if (!attention) return <span className="attn-none">n/a</span>

  const entries = Object.entries(attention)
  const title = entries
    .sort(([, a], [, b]) => b - a)
    .map(([k, v]) => `${TOKEN_LABELS[k] || k}: ${(v * 100).toFixed(0)}%`)
    .join(' · ')

  return (
    <div className="attn-bar" title={title}>
      {entries.map(([k, v]) => (
        <span
          key={k}
          className="attn-seg"
          style={{ width: `${v * 100}%`, background: TOKEN_COLORS[k] || '#555' }}
        />
      ))}
    </div>
  )
}
