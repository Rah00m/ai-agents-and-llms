import { Link } from 'react-router-dom'
import { api } from '../api'
import { Banner, Loading, Pipeline } from '../components'
import { formatTime, githubLabel, modeLabel } from '../format'
import { useAsync } from '../hooks'

export default function Overview() {
  const { data, error, loading, reload } = useAsync(api.overview, [])
  const status = useAsync(api.llmStatus, [])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Screen candidates against a job</h1>
          <p className="lede">
            Six agents read the CVs, job requirements and GitHub profiles, score each candidate, check the
            results and write a report you can download.
          </p>
        </div>
        <span className="actions">
          <Link className="btn" to="/analyze">Start an analysis</Link>
          <Link className="btn secondary" to="/check-cv">Check one CV</Link>
        </span>
      </div>

      <Pipeline />

      {loading && <Loading>Loading overview…</Loading>}
      {error && (
        <div className="section">
          <Banner kind="bad" title="Couldn't load the overview"
            action={<button className="btn secondary" onClick={reload}>Try again</button>}>
            {error.message}
          </Banner>
        </div>
      )}

      {data && (
        <>
          <dl className="facts">
            <div className="fact"><dt>Candidates (CVs read)</dt><dd>{data.candidates}</dd></div>
            <div className="fact"><dt>Jobs</dt><dd>{data.jobs}</dd></div>
            <div className="fact"><dt>GitHub profiles found</dt><dd>{data.github_profiles}</dd></div>
            <div className="fact"><dt>Analyses run</dt><dd>{data.runs}</dd></div>
          </dl>

          {data.data_errors.length > 0 && (
            <div className="section">
              <Banner kind="bad" title="Some input data could not be read">
                <ul>{data.data_errors.map((e) => <li key={e}>{e}</li>)}</ul>
              </Banner>
            </div>
          )}

          <div className="section split">
            <section>
              <h2>Latest analysis</h2>
              {data.last_run ? (
                <dl className="kv">
                  <dt>Job</dt><dd>{data.last_run.job_title} <span className="muted">({data.last_run.job_id})</span></dd>
                  <dt>Finished</dt><dd>{formatTime(data.last_run.started_at)}</dd>
                  <dt>Method</dt><dd>{modeLabel(data.last_run.mode)}</dd>
                  <dt>Top candidate</dt>
                  <dd>{data.last_run.top ? `${data.last_run.top.name}, score ${data.last_run.top.score}` : 'None ranked'}</dd>
                  <dt>Ranked</dt><dd>{data.last_run.ranked} of {data.last_run.candidates}</dd>
                  <dt />
                  <dd><Link to={`/runs/${data.last_run.run_id}`}>Open the results</Link></dd>
                </dl>
              ) : (
                <p className="muted">
                  No analysis yet. Pick a job and run one: it takes seconds with the rule-based parser and a few
                  minutes with a local model.
                </p>
              )}
            </section>

            <section>
              <h2>Where results come from</h2>
              <dl className="kv">
                <dt>Skill extraction</dt>
                <dd>
                  {data.llm.configured_mode === 'ollama' ? `Local LLM (${data.llm.model})` : 'Rule-based parser (no LLM)'}
                </dd>
                <dt>Ollama</dt>
                <dd>
                  {status.loading ? 'Checking…' : status.data?.reachable
                    ? (status.data.model_installed ? 'Running, model installed' : `Running, model ${data.llm.model} missing`)
                    : 'Not running'}
                </dd>
                <dt>GitHub profiles</dt>
                <dd>{githubLabel(data.llm.github_mode === 'live' ? 'live' : 'mock')}</dd>
              </dl>
              {data.llm.github_mode !== 'live' && (
                <p className="muted small" style={{ marginTop: 12 }}>
                  GitHub data comes from a sample file, not the live API. Set GITHUB_MODE=live in backend/.env to
                  use real accounts.
                </p>
              )}
            </section>
          </div>
        </>
      )}
    </>
  )
}
