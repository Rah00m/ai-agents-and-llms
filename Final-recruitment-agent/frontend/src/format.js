// Plain helpers shared by the pages (kept out of components.jsx so that file only exports components).

export const STAGES = [
  { key: 'retrieval', agent: 'Retrievers', does: 'Read CVs, jobs and GitHub profiles in parallel' },
  { key: 'extraction', agent: 'Skill extractor', does: 'Turn each CV into skills, years and evidence' },
  { key: 'matching', agent: 'Matcher', does: 'Score every candidate against the job' },
  { key: 'qa', agent: 'QA reviewer', does: 'Check evidence and years, retry bad results' },
  { key: 'ranking', agent: 'Ranker', does: 'Order the approved candidates' },
  { key: 'report', agent: 'Report writer', does: 'Write the CSV report' },
]

export function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? ''
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(d)
}

export const formatSeconds = (s) => (s == null ? '' : s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(1)} s`)

/** Say exactly what produced the results, so a rule-based run is never mistaken for an LLM run. */
export function modeLabel(mode, model) {
  if (mode === 'ollama') return model ? `Local LLM (${model})` : 'Local LLM (Ollama)'
  return 'Rule-based parser (no LLM)'
}

export function githubLabel(source) {
  if (source === 'live') return 'live GitHub API'
  if (source === 'mock') return 'sample data (offline)'
  return 'no profile found'
}

export const DECISIONS = {
  suitable: { label: 'Suitable', kind: 'ok', mark: '✓' },
  needs_review: { label: 'Needs further review', kind: 'warn', mark: '?' },
  not_suitable: { label: 'Not suitable', kind: 'bad', mark: '✕' },
}

/** A short title for an API error code, so the person sees what kind of problem it was. */
export const ERROR_TITLES = {
  unsupported_type: 'This file type is not supported',
  empty_file: 'The file is empty',
  not_a_pdf: 'This is not a real PDF',
  corrupt_pdf: 'The PDF could not be read',
  pdf_encrypted: 'The PDF is password-protected',
  no_text: 'The PDF has no readable text',
  too_large: 'The file is too large',
  job_not_found: 'That job does not exist',
  ollama_unavailable: 'Ollama is not running',
  model_missing: 'The model is not installed',
  llm_timeout: 'The model took too long',
  llm_invalid_output: 'The model gave an unusable answer',
  llm_unavailable: 'The model is not available',
  network: 'Cannot reach the API',
}
