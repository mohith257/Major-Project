export default function StatusHeader({ rounds, connected }) {
  const latest = rounds[rounds.length - 1]
  return (
    <header className="status-header">
      <h1>Agentic FedGrid</h1>
      <div className="status-pills">
        <span className={`pill ${connected ? 'pill-live' : 'pill-demo'}`}>
          {connected ? 'LIVE' : 'DEMO'}
        </span>
        <span className="pill">Round {latest ? latest.round : '-'}</span>
        <span className="pill">
          Federated val accuracy{' '}
          {latest ? `${(latest.avg_val_accuracy * 100).toFixed(1)}%` : '-'}
        </span>
        <span className="pill">
          {latest ? latest.participants.length : 0} device(s) reporting
        </span>
      </div>
    </header>
  )
}
