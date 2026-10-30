// Observer only: this page reads GET /rounds and GET /incidents and nothing
// else. Attacks are launched from a separate machine and federation runs on
// the nodes by itself; the dashboard just shows what happened. No mock data:
// if the backend is unreachable it says so instead of showing fake numbers.
import { useEffect, useState } from 'react'
import { fetchRounds, fetchIncidents } from './api.js'
import CommandBar from './components/CommandBar.jsx'
import KpiStrip from './components/KpiStrip.jsx'
import Topology from './components/Topology.jsx'
import LiveStream from './components/LiveStream.jsx'
import AccuracyChart from './components/AccuracyChart.jsx'
import DeviceContributions from './components/DeviceContributions.jsx'
import IncidentFeed from './components/IncidentFeed.jsx'
import TablesBrowser from './components/TablesBrowser.jsx'
import AttackButton from './components/AttackButton.jsx'

const POLL_INTERVAL_MS = 3000

const TABS = [
  { id: 'live', label: 'Live' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'tables', label: 'Tables' },
]

export default function App() {
  const [rounds, setRounds] = useState([])
  const [incidents, setIncidents] = useState([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('live')
  const [dbTable, setDbTable] = useState('incidents')

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const [roundsResp, incidentsResp] = await Promise.all([fetchRounds(), fetchIncidents()])
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
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const sortedRounds = [...rounds].sort((a, b) => a.round - b.round)

  return (
    <div className="app soc">
      <CommandBar rounds={sortedRounds} incidents={incidents} connected={connected} error={error} />

      <nav className="soc-tabnav" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={`soc-tabnav-btn ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <KpiStrip rounds={sortedRounds} incidents={incidents} />

      {tab === 'live' && (
        <>
          <AttackButton incidents={incidents} />
          <div className="soc-hero">
            <Topology rounds={sortedRounds} incidents={incidents} />
            <LiveStream incidents={incidents} connected={connected} />
          </div>
        </>
      )}

      {tab === 'analytics' && (
        <>
          <div className="grid">
            <AccuracyChart rounds={sortedRounds} />
            <DeviceContributions rounds={sortedRounds} />
          </div>
          <IncidentFeed incidents={incidents.filter((i) => i.action !== 'NOOP')} />
        </>
      )}

      {tab === 'tables' && (
        <TablesBrowser
          table={dbTable}
          onTable={setDbTable}
          rows={dbTable === 'incidents' ? incidents : [...sortedRounds].reverse()}
          loading={!connected && !error}
          error={error}
        />
      )}
    </div>
  )
}
