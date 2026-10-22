import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { reportUrl } from '../api'
import { Badge, Banner, Chip, Loading, Pipeline, QaBadge, ScoreBar } from '../components'
import { formatTime, githubLabel, modeLabel } from '../format'
import { useRun } from '../hooks'

const pct = (v) => `${Math.round(v * 100)}%`

function Dossier({ cand, job, weights }) {
  const m = cand.match
  const ranked = cand.status === 'ranked' && m
  const noPreferred = job.preferred_skills.length === 0
  const parts = ranked && [
    { label: 'Required skills', value: m.required_score, weight: weights.required },
    { label: 'Experience', value: m.experience_score, weight: weights.experience },
    { label: 'Preferred skills', value: m.preferred_score, weight: weights.preferred, unused: noPreferred },
  ]
  const evidence = cand.profile ? cand.profile.skills.map((s) => [s, cand.profile.evidence[s]]) : []

  return (
    <div className="dossier" aria-live="polite">
      <div className="dossier-top">
        <div>
          <h2>{cand.name}</h2>
          <p className="muted small">
            {cand.candidate_id}{cand.rank ? `, ranked ${cand.rank}` : ''}
          </p>
        </div>
        {ranked && <div className="big-score">{m.score.toFixed(1)}<small>out of 100</small></div>}
      </div>

      {!ranked && (
        <Banner kind={cand.status === 'failed' ? 'bad' : 'warn'}
          title={cand.status === 'failed' ? 'This candidate could not be processed' : 'Needs manual review'}>
          {cand.status === 'failed'
            ? cand.error
            : cand.qa?.issues.filter((i) => i.severity === 'error').map((i) => i.message).join(' ')}
          {' '}They are not included in the ranking.
        </Banner>
      )}

      {ranked && (
        <>
          <div className="group">
            <h3>How the score is built</h3>
            <div className="parts">
              {parts.map((p) => (
                <div className="part" key={p.label}>
                  <span>
                    {p.label}{' '}
                    <span className="part-weight">
                      {p.unused ? '(not used: the job lists none)' : `(weight ${pct(p.weight)})`}
                    </span>
                  </span>
                  <span className="part-val">{pct(p.value)}</span>
                  <ScoreBar value={p.value * 100} label={`${p.label}: ${pct(p.value)}`} />
                </div>
              ))}
            </div>
          </div>

          <div className="group">
            <h3>Required skills</h3>
            <div className="chips">
              {m.matched_required.map((s) => <Chip key={s} kind="ok">{s}</Chip>)}
              {m.partial_required.map((s) => <Chip key={s} kind="warn">{s} (basic level)</Chip>)}
              {m.missing_required.map((s) => <Chip key={s} kind="bad">{s} missing</Chip>)}
            </div>
          </div>

          {job.preferred_skills.length > 0 && (
            <div className="group">
              <h3>Preferred skills</h3>
              <div className="chips">
                {m.matched_preferred.map((s) => <Chip key={s} kind="ok">{s}</Chip>)}
                {m.missing_preferred.map((s) => <Chip key={s}>{s} not found</Chip>)}
              </div>
            </div>
          )}

          <div className="group">
            <h3>Why this score</h3>
            <p>{m.explanation}</p>
          </div>
        </>
      )}

      {cand.profile && (
        <div className="group">
          <h3>Profile read from the CV</h3>
          <dl className="kv">
            <dt>Experience</dt>
            <dd>{cand.profile.experience_years != null ? `${cand.profile.experience_years} years` : 'Not stated'}</dd>
            <dt>Education</dt>
            <dd>{cand.profile.education.length ? cand.profile.education.join('; ') : 'Not found'}</dd>
            <dt>GitHub</dt>
            <dd>
              {cand.github_languages.length ? cand.github_languages.join(', ') : 'No languages'}{' '}
              <span className="muted">({githubLabel(cand.github_source)})</span>
              {ranked && m.github_supported.length > 0 && <> , supports {m.github_supported.join(', ')}</>}
            </dd>
          </dl>
        </div>
      )}

      {evidence.length > 0 && (
        <details className="group" open>
          <summary><h3 style={{ display: 'inline' }}>Evidence from the CV</h3></summary>
          <ul className="evidence" style={{ marginTop: 12 }}>
            {evidence.map(([skill, quote]) => {
              // a long comma-separated line is the CV's Skills list, not an example of the skill being used
              const listOnly = quote && quote.split(',').length >= 4
              return (
                <li key={skill}>
                  <span className="skill">{skill}</span>
                  {!quote && <span className="muted"> no quote found</span>}
                  {listOnly && <span className="muted"> listed in the skills section only, no example of use</span>}
                  {quote && !listOnly && <q>{quote}</q>}
                </li>
              )
            })}
          </ul>
        </details>
      )}

      {cand.qa && (
        <div className="group">
          <h3>Quality check <QaBadge status={cand.qa.status} /></h3>
          {cand.qa.issues.length === 0 ? (
            <p className="muted" style={{ marginTop: 8 }}>No problems found.</p>
          ) : (
            <ul className="issues" style={{ marginTop: 10 }}>
              {cand.qa.issues.map((i, n) => (
                <li key={n}>
                  <Chip kind={i.severity === 'error' ? 'bad' : 'warn'}>{i.severity === 'error' ? 'Error' : 'Warning'}</Chip>
                  <span>{i.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

// keyed by run id: opening another run starts with a clean selection and a clean poll
export default function RunPage() {
  const { runId } = useParams()
  return <Run key={runId} runId={runId} />
}

function Run({ runId }) {
  const { data, error, loading } = useRun(runId)
  const [selectedId, setSelectedId] = useState(null)

  if (loading && !data) return <Loading>Loading this analysis…</Loading>
  if (!data) {
    return (
      <div className="empty">
        <h2>{error?.status === 404 ? "We can't find this analysis" : "Couldn't load this analysis"}</h2>
        <p className="muted">{error?.message}</p>
        <Link className="btn" to="/runs">See all analyses</Link>
      </div>
    )
  }

  const result = data.result
  const all = result?.results ?? []
  const ranked = all.filter((r) => r.status === 'ranked')
  const others = all.filter((r) => r.status !== 'ranked')
  const selected = all.find((r) => r.candidate_id === selectedId) ?? ranked[0] ?? others[0]
  const requiredCount = result?.job.required_skills.length ?? 0
  const notes = result ? [...result.errors, ...result.warnings] : []
  const canDownload = data.status === 'done' && result?.report_file
  const statusBadge = { running: <Badge kind="info">Running</Badge>, done: <Badge kind="ok">Finished</Badge>, failed: <Badge kind="bad">Failed</Badge> }[data.status]

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{result ? result.job.title : `Job ${data.job_id}`} {statusBadge}</h1>
          <div className="meta">
            <span><b>Job</b> {data.job_id}</span>
            <span><b>Method</b> {modeLabel(data.mode, result?.model)}</span>
            <span><b>Started</b> {formatTime(data.started_at)}</span>
            {result && <span><b>Took</b> {result.total_seconds} s</span>}
            <span><b>Run</b> {data.run_id}</span>
          </div>
        </div>
        {canDownload ? (
          <a className="btn" href={reportUrl(runId)} download>Download report (CSV)</a>
        ) : (
          <span className="btn" aria-disabled="true" title="The report is written when the run finishes">
            Download report (CSV)
          </span>
        )}
      </div>

      <section aria-labelledby="wf-h">
        <h2 id="wf-h">Workflow</h2>
        <Pipeline stages={data.stages} />
      </section>

      {data.status === 'failed' && (
        <div className="section">
          <Banner kind="bad" title="The analysis stopped"
            action={<Link className="btn secondary" to="/analyze">Try again</Link>}>
            {data.error}
          </Banner>
        </div>
      )}

      {error && data.status === 'running' && (
        <div className="section">
          <Banner kind="warn" title="Lost contact with the API">{error.message}</Banner>
        </div>
      )}

      {data.status === 'running' && (
        <p className="loading" style={{ marginTop: 32 }}>
          Working through the steps above. Results appear here as soon as the run finishes.
        </p>
      )}

      {result && (
        <div className="section">
          <p className="muted" style={{ marginBottom: 16 }}>
            {ranked.length} of {all.length} candidates ranked
            {others.length > 0 ? `, ${others.length} need attention` : ''}.
          </p>

          {all.length === 0 ? (
            <div className="empty"><h2>No candidates were analyzed</h2><p className="muted">Add CV PDFs to backend/data/cvs and run again.</p></div>
          ) : (
            <div className="run-grid">
              <div>
                <h2 style={{ marginBottom: 14 }}>Ranking</h2>
                <table className="ledger">
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Candidate</th>
                      <th scope="col">Score</th>
                      <th scope="col" className="num hide-sm">Required skills</th>
                      <th scope="col" className="hide-sm">Quality check</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranked.map((r) => (
                      <tr key={r.candidate_id} className={selected?.candidate_id === r.candidate_id ? 'selected' : ''}
                        aria-selected={selected?.candidate_id === r.candidate_id}
                        onClick={() => setSelectedId(r.candidate_id)}>
                        <td className="rank">{r.rank}</td>
                        <td>
                          <button className="linklike" onClick={() => setSelectedId(r.candidate_id)}>{r.name}</button>
                          <div className="cand-id">{r.candidate_id}</div>
                        </td>
                        <td>
                          <div className="score-cell">
                            <span className="score-num">{r.match.score.toFixed(1)}</span>
                            <ScoreBar value={r.match.score} />
                          </div>
                        </td>
                        <td className="num hide-sm">
                          {r.match.matched_required.length}/{requiredCount}
                          {r.match.partial_required.length > 0 && <span className="muted small"> +{r.match.partial_required.length} basic</span>}
                        </td>
                        <td className="hide-sm"><QaBadge status={r.qa.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {others.length > 0 && (
                  <div className="section">
                    <h2>Needs attention</h2>
                    <table className="ledger">
                      <tbody>
                        {others.map((r) => (
                          <tr key={r.candidate_id} className={selected?.candidate_id === r.candidate_id ? 'selected' : ''}
                            onClick={() => setSelectedId(r.candidate_id)}>
                            <td>
                              <button className="linklike" onClick={() => setSelectedId(r.candidate_id)}>{r.name}</button>
                              <div className="cand-id">{r.candidate_id}</div>
                            </td>
                            <td><Badge kind={r.status === 'failed' ? 'bad' : 'warn'}>{r.status === 'failed' ? 'Failed' : 'Needs manual review'}</Badge></td>
                            <td className="muted small">{r.error || r.qa?.issues.find((i) => i.severity === 'error')?.message}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="sticky">
                {selected && <Dossier cand={selected} job={result.job} weights={result.weights} />}
              </div>
            </div>
          )}

          {notes.length > 0 && (
            <details className="fold">
              <summary>{notes.length} {notes.length === 1 ? 'note' : 'notes'} from this run</summary>
              <ul>{notes.map((n) => <li key={n}>{n}</li>)}</ul>
            </details>
          )}
        </div>
      )}
    </>
  )
}
