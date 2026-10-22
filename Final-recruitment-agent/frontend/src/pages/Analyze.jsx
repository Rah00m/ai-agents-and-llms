import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Banner, Chip, Loading, Spinner } from '../components'
import { useAsync } from '../hooks'

export default function Analyze() {
  const navigate = useNavigate()
  const jobs = useAsync(api.jobs, [])
  const llm = useAsync(api.llmStatus, [])
  const [jobId, setJobId] = useState(null)
  const [pickedMode, setPickedMode] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState(null)

  const ollamaReady = !!(llm.data?.reachable && llm.data?.model_installed)
  // until the person chooses, prefer the real model when it is available
  const mode = pickedMode ?? (ollamaReady ? 'ollama' : 'mock')
  const canRun = jobId && !submitting && !(mode === 'ollama' && !ollamaReady)

  async function run() {
    setSubmitting(true)
    setFailure(null)
    try {
      const started = await api.analyze(jobId, mode)
      navigate(`/runs/${started.run_id}`)
    } catch (e) {
      setFailure(e)
      setSubmitting(false)
    }
  }

  const ollamaNote = llm.loading
    ? 'Checking Ollama…'
    : !llm.data?.reachable
      ? 'Ollama is not running. Start it with “ollama serve”.'
      : !llm.data.model_installed
        ? `Model ${llm.data.model} is not installed. Run “ollama pull ${llm.data.model}”.`
        : `${llm.data.model} is ready.`

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Choose a job</h1>
          <p className="lede">Every CV is scored against the job you pick. Results appear as soon as the run finishes.</p>
        </div>
      </div>

      {failure && (
        <div style={{ marginBottom: 24 }}>
          <Banner kind="bad" title="Couldn't start the analysis"
            action={failure.details?.run_id && <Link className="btn secondary" to={`/runs/${failure.details.run_id}`}>View running analysis</Link>}>
            {failure.message}
          </Banner>
        </div>
      )}

      <div className="split">
        <section aria-labelledby="jobs-h">
          <h2 id="jobs-h" className="sr-only">Jobs</h2>
          {jobs.loading && <Loading>Loading jobs…</Loading>}
          {jobs.error && (
            <Banner kind="bad" title="Couldn't load the jobs"
              action={<button className="btn secondary" onClick={jobs.reload}>Try again</button>}>
              {jobs.error.message}
            </Banner>
          )}
          {jobs.data && (
            <div className="choices" role="radiogroup" aria-label="Job">
              {jobs.data.map((j) => (
                <label key={j.job_id} className={`choice ${jobId === j.job_id ? 'selected' : ''}`}>
                  <input type="radio" name="job" checked={jobId === j.job_id} onChange={() => setJobId(j.job_id)} />
                  <span className="choice-body">
                    <span className="choice-title">{j.title}<span className="id">{j.job_id}</span></span>
                    <span className="chips" aria-label="Required skills">
                      {j.required_skills.map((s) => <Chip key={s}>{s}</Chip>)}
                    </span>
                    <span className="muted small">
                      At least {j.min_years_experience} years of experience
                      {j.preferred_skills.length > 0 && `. Preferred: ${j.preferred_skills.join(', ')}`}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </section>

        <aside className="aside" aria-labelledby="how-h">
          <h2 id="how-h">How to read the CVs</h2>
          <div className="choices" role="radiogroup" aria-label="Method">
            <label className={`choice ${mode === 'ollama' ? 'selected' : ''} ${!ollamaReady ? 'disabled' : ''}`}>
              <input type="radio" name="mode" checked={mode === 'ollama'} disabled={!ollamaReady}
                onChange={() => setPickedMode('ollama')} />
              <span className="choice-body">
                <span className="choice-title">Local LLM (Ollama)</span>
                <span className="muted small">
                  A model running on this computer reads each CV. Handles any CV layout, and takes a few minutes.
                </span>
                <span className="small" style={{ color: ollamaReady ? 'var(--ok)' : 'var(--bad)' }}>{ollamaNote}</span>
              </span>
            </label>
            <label className={`choice ${mode === 'mock' ? 'selected' : ''}`}>
              <input type="radio" name="mode" checked={mode === 'mock'} onChange={() => setPickedMode('mock')} />
              <span className="choice-body">
                <span className="choice-title">Rule-based parser</span>
                <span className="muted small">
                  Fixed rules read the CV sections. No AI model is involved. Instant, but only works for CVs with a
                  “Skills” section.
                </span>
              </span>
            </label>
          </div>
          <button className="btn" disabled={!canRun} onClick={run}>
            {submitting ? <><Spinner label="Starting" /> Starting…</> : 'Run analysis'}
          </button>
          {!jobId && <p className="muted small" style={{ marginTop: 10 }}>Choose a job to continue.</p>}
        </aside>
      </div>
    </>
  )
}
