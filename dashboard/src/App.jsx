import { useEffect, useState } from 'react'
import { fetchRounds, fetchIncidents } from './api.js'
import { MOCK_ROUNDS, MOCK_INCIDENTS } from './mockData.js'
import StatusHeader from './components/StatusHeader.jsx'
import AccuracyChart from './components/AccuracyChart.jsx'
import DeviceContributions from './components/DeviceContributions.jsx'
import LiveAssessment from './components/LiveAssessment.jsx'
import IncidentFeed from './components/IncidentFeed.jsx'

const POLL_INTERVAL_MS = 5000

export default function App() {
  const [rounds, setRounds] = useState([])
  const [incidents, setIncidents] = useState([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const [roundsResp, incidentsResp] = await Promise.all([
          fetchRounds(),
          fetchIncidents(),
        ])
        if (cancelled) return
        setRounds(roundsResp.rounds)
        setIncidents(incidentsResp.incidents)
        setConnected(true)
        setError(null)
      } catch (e) {
        if (cancelled) return
        setConnected(false)
        setError(e.message)
      }
    }

    poll()
    const id = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const displayRounds = connected ? rounds : MOCK_ROUNDS
  const displayIncidents = connected ? incidents : MOCK_INCIDENTS
  const sortedRounds = [...displayRounds].sort((a, b) => a.round - b.round)

  return (
    <div className="app">
      {!connected && (
        <div className="demo-banner">
          DEMO DATA -- not connected to a live backend{error ? ` (${error})` : ''}.
          Set VITE_API_BASE_URL / VITE_API_KEY in dashboard/.env.local and
          reload to see real telemetry.
        </div>
      )}
      <StatusHeader rounds={sortedRounds} connected={connected} />
      <LiveAssessment incidents={displayIncidents} connected={connected} />
      <div className="grid">
        <AccuracyChart rounds={sortedRounds} />
        <DeviceContributions rounds={sortedRounds} />
      </div>
      <IncidentFeed incidents={displayIncidents} />
    </div>
  )
}
