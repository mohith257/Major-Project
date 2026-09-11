import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'

export default function DeviceContributions({ rounds }) {
  const counts = {}
  rounds.forEach((r) => {
    ;(r.participants || []).forEach((d) => {
      counts[d] = (counts[d] || 0) + 1
    })
  })
  const data = Object.entries(counts)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([device_id, rounds_participated]) => ({ device_id, rounds_participated }))

  return (
    <div className="card">
      <h2>Device Participation</h2>
      <p className="card-subtitle">Rounds each edge device has contributed an update to.</p>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid-line)" />
          <XAxis dataKey="device_id" />
          <YAxis allowDecimals={false} />
          <Tooltip />
          <Bar dataKey="rounds_participated" fill="var(--accent-2)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
