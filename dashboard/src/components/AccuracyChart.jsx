import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'

export default function AccuracyChart({ rounds }) {
  const data = rounds.map((r) => ({
    round: r.round,
    accuracy: Math.round(r.avg_val_accuracy * 1000) / 10, // percent, 1 decimal
  }))

  return (
    <div className="card">
      <h2>Federated Validation Accuracy</h2>
      <p className="card-subtitle">
        Sample-weighted average of each device&apos;s own local validation
        accuracy per round -- not an independent global test-set score, the
        cloud never runs the model itself.
      </p>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid-line)" />
          <XAxis
            dataKey="round"
            label={{ value: 'Round', position: 'insideBottom', offset: -4 }}
          />
          <YAxis domain={[0, 100]} unit="%" />
          <Tooltip formatter={(v) => [`${v}%`, 'Accuracy']} labelFormatter={(r) => `Round ${r}`} />
          <Line type="monotone" dataKey="accuracy" stroke="var(--accent)" strokeWidth={2} dot={{ r: 3 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
