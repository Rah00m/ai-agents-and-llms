import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge, Banner, Loading } from '../components'
import { formatTime, modeLabel } from '../format'
import { useAsync } from '../hooks'

const STATUS = { done: <Badge kind="ok">Finished</Badge>, running: <Badge kind="info">Running</Badge>, failed: <Badge kind="bad">Failed</Badge> }

export default function Runs() {
  const { data, error, loading, reload } = useAsync(api.runs, [])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>History</h1>
          <p className="lede">Every analysis you have run, newest first. Open one to see its ranking and download its report.</p>
        </div>
        <Link className="btn" to="/analyze">New analysis</Link>
      </div>

      {loading && <Loading>Loading history…</Loading>}
      {error && (
        <Banner kind="bad" title="Couldn't load the history"
          action={<button className="btn secondary" onClick={reload}>Try again</button>}>
          {error.message}
        </Banner>
      )}
      {data && data.length === 0 && (
        <div className="empty">
          <h2>No analyses yet</h2>
          <p className="muted">Pick a job and run your first analysis. It will show up here.</p>
          <Link className="btn" to="/analyze">Choose a job</Link>
        </div>
      )}
      {data && data.length > 0 && (
        <table className="ledger">
          <thead>
            <tr>
              <th scope="col">Job</th>
              <th scope="col">Started</th>
              <th scope="col" className="hide-sm">Method</th>
              <th scope="col">Status</th>
              <th scope="col">Top candidate</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.run_id}>
                <td>
                  <Link to={`/runs/${r.run_id}`}><b>{r.job_title || r.job_id}</b></Link>
                  <div className="cand-id">{r.job_id}</div>
                </td>
                <td>{formatTime(r.started_at)}</td>
                <td className="hide-sm">{modeLabel(r.mode)}</td>
                <td>{STATUS[r.status]}</td>
                <td>{r.top ? `${r.top.name} (${r.top.score})` : <span className="muted">None</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
