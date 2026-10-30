// Raw DynamoDB row browser. Shows the actual rows the backend returns from
// the two readable tables -- incidents (IncidentsTable) and rounds
// (RoundsTable) -- as a generic dynamic-column table, newest first. This is
// the "show me the real data" view: no derived numbers, just the stored rows.
//
// roundstate (RoundStateTable) has no GET endpoint, so it's not listed here.
// Adding it needs a new read Lambda + redeploy.
import { useMemo } from 'react'

const TABLES = [
  { id: 'incidents', label: 'incidents', help: 'IncidentsTable — one row per autonomous decision each node logged.' },
  { id: 'rounds', label: 'rounds', help: 'RoundsTable — one row per completed federated-averaging round.' },
]

function cell(v) {
  if (v == null) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  if (typeof v === 'number' && v > 1e12) {
    // epoch ms -> readable, but keep the raw number too
    return `${v} (${new Date(v).toLocaleString()})`
  }
  return String(v)
}

export default function TablesBrowser({ table, onTable, rows, loading, error }) {
  const columns = useMemo(() => {
    const seen = []
    for (const r of rows) {
      for (const k of Object.keys(r)) if (!seen.includes(k)) seen.push(k)
    }
    return seen
  }, [rows])

  const active = TABLES.find((t) => t.id === table) || TABLES[0]

  return (
    <div className="card">
      <div className="tbl-head">
        <div>
          <h2>DynamoDB — raw rows</h2>
          <p className="card-subtitle">{active.help}</p>
        </div>
        <div className="tbl-switch">
          {TABLES.map((t) => (
            <button
              key={t.id}
              className={`tbl-switch-btn ${t.id === table ? 'active' : ''}`}
              onClick={() => onTable(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="tbl-meta">
        {loading ? 'loading…'
          : error ? <span className="tbl-err">backend unreachable — {error}</span>
          : `${rows.length} row${rows.length === 1 ? '' : 's'} · ${columns.length} columns`}
      </div>

      <div className="table-wrap tbl-scroll">
        <table className="tbl-raw">
          <thead>
            <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c} className="tbl-cell" title={cell(r[c])}>{cell(r[c])}</td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && !loading && (
              <tr><td className="empty" colSpan={Math.max(columns.length, 1)}>No rows.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
