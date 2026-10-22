// All backend calls live here. In development Vite proxies /api to FastAPI on port 8000.
export const API = import.meta.env.VITE_API_URL || '/api'

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'error', details = null } = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

function messageFrom(body, res) {
  const d = body?.detail
  if (!d) {
    return res.status >= 500
      ? `The API did not respond properly (status ${res.status}). Is the backend running on port 8000?`
      : `Request failed (status ${res.status}).`
  }
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((e) => e.msg).join('; ') // FastAPI validation errors
  return d.message || `Request failed (status ${res.status}).`
}

async function request(path, options = {}) {
  let res
  try {
    // a FormData body must set its own multipart header (with the boundary), so only JSON gets one
    const isForm = options.body instanceof FormData
    res = await fetch(`${API}${path}`, {
      headers: isForm ? {} : { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new ApiError(
      "Can't reach the API. Start the backend with: uvicorn app.main:app --port 8000",
      { code: 'network' },
    )
  }
  if (!res.ok) {
    let body = null
    try {
      body = await res.json()
    } catch {
      /* no JSON body */
    }
    throw new ApiError(messageFrom(body, res), {
      status: res.status,
      code: body?.detail?.code || 'error',
      details: body?.detail || null,
    })
  }
  return res.json()
}

export const api = {
  overview: () => request('/overview'),
  jobs: () => request('/jobs'),
  llmStatus: () => request('/llm/status'),
  runs: () => request('/runs'),
  analyze: (jobId, mode) => request('/analyze', { method: 'POST', body: JSON.stringify({ job_id: jobId, mode }) }),
  analyzeCv: (file, jobId, mode) => {
    const form = new FormData()
    form.append('file', file)
    form.append('job_id', jobId)
    if (mode) form.append('mode', mode)
    return request('/analyze-cv', { method: 'POST', body: form })
  },
  results: (runId) => request(`/results/${encodeURIComponent(runId)}`),
}

export const reportUrl = (runId) => `${API}/reports/${encodeURIComponent(runId)}`
