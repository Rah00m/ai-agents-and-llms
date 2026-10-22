import { useRef, useState } from 'react'
import { api } from '../api'
import { Banner, Chip, Loading, ScoreBar, Spinner } from '../components'
import { DECISIONS, ERROR_TITLES, formatSeconds, modeLabel } from '../format'
import { useAsync } from '../hooks'

const pct = (v) => `${Math.round(v * 100)}%`

function List({ items, empty }) {
  if (!items.length) return <p className="muted">{empty}</p>
  return <ul className="plain">{items.map((t) => <li key={t}>{t}</li>)}</ul>
}

function Result({ r }) {
  const d = r.decision
  const kind = DECISIONS[d.label]
  const noPreferred = r.job.preferred_skills.length === 0
  const parts = [
    { label: 'Required skills', value: r.match.required_score, weight: r.weights.required },
    { label: 'Experience', value: r.match.experience_score, weight: r.weights.experience },
    { label: 'Preferred skills', value: r.match.preferred_score, weight: r.weights.preferred, unused: noPreferred },
  ]
  const missingPreferred = r.match.missing_preferred

  return (
    <div className="dossier" aria-live="polite" data-testid="result">
      <div className={`verdict verdict-${kind.kind}`}>
        <span className="verdict-mark" aria-hidden="true">{kind.mark}</span>
        <div>
          <div className="verdict-label" data-testid="decision">{kind.label}</div>
          <div>{d.summary}</div>
        </div>
      </div>

      <p className="muted small">
        {r.candidate_name} · {r.filename} · for <b>{r.job.title}</b> ({r.job.job_id})
      </p>

      <div className="group">
        <h3>Why</h3>
        <ul className="plain">{d.reasons.map((t) => <li key={t}>{t}</li>)}</ul>
      </div>

      <div className="group">
        <h3>Required skills</h3>
        <div className="chips">
          {d.matched_skills.map((s) => <Chip key={s} kind="ok">{s}</Chip>)}
          {d.partial_skills.map((s) => <Chip key={s} kind="warn">{s} (basic level)</Chip>)}
          {d.missing_required.map((s) => <Chip key={s} kind="bad">{s} missing</Chip>)}
        </div>
      </div>

      {!noPreferred && (
        <div className="group">
          <h3>Preferred skills</h3>
          <div className="chips">
            {d.matched_preferred.map((s) => <Chip key={s} kind="ok">{s}</Chip>)}
            {missingPreferred.map((s) => <Chip key={s}>{s} not found</Chip>)}
          </div>
        </div>
      )}

      <div className="group">
        <h3>Experience</h3>
        <p>
          {d.years_found != null ? `${d.years_found} years stated` : 'Years of experience not stated'}
          {' '}· this job asks for at least {d.years_required}
        </p>
        <h3 style={{ marginTop: 14 }}>Relevant experience</h3>
        <List items={d.relevant_experience} empty="No experience entry that uses a required skill was found." />
      </div>

      <div className="group">
        <h3>Missing information</h3>
        <List items={d.missing_information} empty="Nothing important is missing from the CV." />
      </div>

      <div className="group">
        <h3>Matching score</h3>
        <div className="big-score inline">{r.match.score.toFixed(1)}<small>out of 100</small></div>
        <div className="parts" style={{ marginTop: 12 }}>
          {parts.map((p) => (
            <div className="part" key={p.label}>
              <span>
                {p.label}{' '}
                <span className="part-weight">{p.unused ? '(not used: the job lists none)' : `(weight ${pct(p.weight)})`}</span>
              </span>
              <span className="part-val">{pct(p.value)}</span>
              <ScoreBar value={p.value * 100} label={`${p.label}: ${pct(p.value)}`} />
            </div>
          ))}
        </div>
      </div>

      <details className="group">
        <summary><h3 style={{ display: 'inline' }}>Profile read from the CV</h3></summary>
        <dl className="kv" style={{ marginTop: 12 }}>
          <dt>Skills</dt>
          <dd>{r.profile.skills.length ? r.profile.skills.join(', ') : 'None found'}</dd>
          <dt>Education</dt>
          <dd>{r.profile.education.length ? r.profile.education.join('; ') : 'Not found'}</dd>
          <dt>Work experience</dt>
          <dd>{r.profile.experience.length ? r.profile.experience.join(' | ') : 'Not found'}</dd>
        </dl>
      </details>

      {r.qa.issues.length > 0 && (
        <div className="group">
          <h3>Quality check notes</h3>
          <ul className="issues" style={{ marginTop: 10 }}>
            {r.qa.issues.map((i, n) => (
              <li key={n}>
                <Chip kind={i.severity === 'error' ? 'bad' : 'warn'}>{i.severity === 'error' ? 'Error' : 'Warning'}</Chip>
                <span>{i.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="muted small">
        Method: {modeLabel(r.mode, r.model)} · {formatSeconds(r.seconds)} · {r.warnings.join(' ')}
      </p>
    </div>
  )
}

export default function CheckCv() {
  const jobs = useAsync(api.jobs, [])
  const llm = useAsync(api.llmStatus, [])
  const [jobId, setJobId] = useState('')
  const [file, setFile] = useState(null)
  const [pickedMode, setPickedMode] = useState(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [failure, setFailure] = useState(null)
  const input = useRef(null)

  const ollamaReady = !!(llm.data?.reachable && llm.data?.model_installed)
  const mode = pickedMode ?? (ollamaReady ? 'ollama' : 'mock')
  const canRun = jobId && file && !busy && !(mode === 'ollama' && !ollamaReady)

  // a result belongs to one job and one file: change either and the old answer is cleared
  function pickJob(id) { setJobId(id); setResult(null); setFailure(null) }
  function pickFile(f) { setFile(f); setResult(null); setFailure(null) }

  async function run(e) {
    e.preventDefault()
    setBusy(true)
    setFailure(null)
    setResult(null)
    try {
      setResult(await api.analyzeCv(file, jobId, mode))
    } catch (err) {
      setFailure(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Check one CV</h1>
          <p className="lede">
            Pick the job, upload one CV as a PDF, and get a decision for that job with the reasons.
            Nothing is saved and your batch analyses are not affected.
          </p>
        </div>
      </div>

      <form className="split" onSubmit={run}>
        <section aria-labelledby="job-h">
          <h2 id="job-h">1. Choose the job</h2>
          {jobs.loading && <Loading>Loading jobs…</Loading>}
          {jobs.error && (
            <Banner kind="bad" title="Couldn't load the jobs"
              action={<button type="button" className="btn secondary" onClick={jobs.reload}>Try again</button>}>
              {jobs.error.message}
            </Banner>
          )}
          {jobs.data && (
            <div className="choices" role="radiogroup" aria-label="Job">
              {jobs.data.map((j) => (
                <label key={j.job_id} className={`choice ${jobId === j.job_id ? 'selected' : ''}`}>
                  <input type="radio" name="job" checked={jobId === j.job_id} onChange={() => pickJob(j.job_id)} />
                  <span className="choice-body">
                    <span className="choice-title">{j.title}<span className="id">{j.job_id}</span></span>
                    <span className="chips" aria-label="Required skills">
                      {j.required_skills.map((s) => <Chip key={s}>{s}</Chip>)}
                    </span>
                    <span className="muted small">
                      At least {j.min_years_experience} years
                      {j.preferred_skills.length > 0 && `. Preferred: ${j.preferred_skills.join(', ')}`}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </section>

        <aside className="aside" aria-labelledby="cv-h">
          <h2 id="cv-h">2. Upload the CV</h2>
          <label className="file-pick">
            <span className="btn secondary">{file ? 'Choose another file' : 'Choose a PDF'}</span>
            <input ref={input} type="file" accept="application/pdf,.pdf" aria-label="CV file (PDF)"
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
            <span className="muted small" data-testid="file-name">{file ? `${file.name} (${Math.max(1, Math.round(file.size / 1024))} KB)` : 'No file chosen'}</span>
          </label>

          <h2 style={{ marginTop: 24 }}>3. Method</h2>
          <div className="choices" role="radiogroup" aria-label="Method">
            <label className={`choice ${mode === 'ollama' ? 'selected' : ''} ${!ollamaReady ? 'disabled' : ''}`}>
              <input type="radio" name="mode" checked={mode === 'ollama'} disabled={!ollamaReady} onChange={() => setPickedMode('ollama')} />
              <span className="choice-body">
                <span className="choice-title">Local LLM (Ollama)</span>
                <span className="small" style={{ color: ollamaReady ? 'var(--ok)' : 'var(--bad)' }}>
                  {llm.loading ? 'Checking Ollama…' : ollamaReady ? `${llm.data.model} is ready.` : 'Not available: Ollama is not running or the model is not installed.'}
                </span>
              </span>
            </label>
            <label className={`choice ${mode === 'mock' ? 'selected' : ''}`}>
              <input type="radio" name="mode" checked={mode === 'mock'} onChange={() => setPickedMode('mock')} />
              <span className="choice-body">
                <span className="choice-title">Rule-based parser</span>
                <span className="muted small">No AI model. Works best on CVs with a “Skills” section.</span>
              </span>
            </label>
          </div>

          <button className="btn" type="submit" disabled={!canRun}>
            {busy ? <><Spinner label="Checking" /> Checking…</> : 'Check this CV'}
          </button>
          {!jobId && <p className="muted small" style={{ marginTop: 10 }}>Choose a job first.</p>}
          {jobId && !file && <p className="muted small" style={{ marginTop: 10 }}>Choose a CV file.</p>}
        </aside>
      </form>

      <div className="section">
        {failure && (
          <Banner kind="bad" title={ERROR_TITLES[failure.code] || "Couldn't check this CV"}>
            {failure.message}
          </Banner>
        )}
        {result && <Result r={result} />}
      </div>
    </>
  )
}
