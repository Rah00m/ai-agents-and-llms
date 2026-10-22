import { useEffect, useRef } from 'react'

import { STAGES, formatSeconds } from './format'

// ---------------------------------------------------------------- small pieces

const ICONS = { ok: '✓', warn: '~', bad: '✕', info: 'i', neutral: '' }

export function Chip({ kind = 'neutral', children }) {
  return (
    <span className={`chip chip-${kind}`}>
      {ICONS[kind] && <span aria-hidden="true" className="chip-icon">{ICONS[kind]}</span>}
      {children}
    </span>
  )
}

export function Badge({ kind = 'neutral', children }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}

export function QaBadge({ status }) {
  if (status === 'approved') return <Badge kind="ok">Approved</Badge>
  if (status === 'approved_with_warnings') return <Badge kind="warn">Approved with warnings</Badge>
  if (status === 'rejected') return <Badge kind="bad">Rejected</Badge>
  return <Badge>Not reviewed</Badge>
}

export function ScoreBar({ value, label }) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <span className="bar" role="img" aria-label={label || `${pct} out of 100`}>
      <span className="bar-fill" style={{ width: `${pct}%` }} />
    </span>
  )
}

export function Spinner({ label = 'Loading' }) {
  return <span className="spinner" role="status" aria-label={label} />
}

export function Banner({ kind = 'info', title, children, action }) {
  return (
    <div className={`banner banner-${kind}`} role={kind === 'bad' ? 'alert' : 'status'}>
      <span className="banner-icon" aria-hidden="true">{ICONS[kind] || 'i'}</span>
      <div className="banner-body">
        {title && <strong>{title}</strong>}
        {children && <div>{children}</div>}
      </div>
      {action}
    </div>
  )
}

export function Loading({ children = 'Loading…' }) {
  return (
    <p className="loading">
      <Spinner /> {children}
    </p>
  )
}

// ---------------------------------------------------------------- the pipeline

const STATE_TEXT = { pending: 'Waiting', running: 'Running', done: 'Done', failed: 'Failed' }

/**
 * The six steps of a run. With `stages` (from GET /results) it shows live status;
 * without it, it just describes the steps.
 */
export function Pipeline({ stages }) {
  const live = useRef(null)

  // announce the running step to screen readers without re-reading the whole list
  useEffect(() => {
    if (!stages || !live.current) return
    const running = STAGES.find((s) => stages[s.key]?.status === 'running')
    live.current.textContent = running ? `${running.agent} is running` : ''
  }, [stages])

  return (
    <>
      <ol className="pipeline">
        {STAGES.map((s, i) => {
          const st = stages?.[s.key]
          const state = st?.status || 'idle'
          return (
            <li key={s.key} className={`station station-${state}`}>
              <span className="marker" aria-hidden="true">
                {state === 'done' ? '✓' : state === 'failed' ? '✕' : i + 1}
              </span>
              <span className="station-name">{s.agent}</span>
              {st ? (
                <>
                  <span className="station-state">
                    {STATE_TEXT[state]}
                    {state === 'done' && st.seconds != null ? ` in ${formatSeconds(st.seconds)}` : ''}
                  </span>
                  {/* live detail only while the step runs; otherwise say what the step does */}
                  <span className="station-detail">{state === 'running' ? st.detail || s.does : s.does}</span>
                </>
              ) : (
                <span className="station-detail">{s.does}</span>
              )}
            </li>
          )
        })}
      </ol>
      <span className="sr-only" aria-live="polite" ref={live} />
    </>
  )
}
