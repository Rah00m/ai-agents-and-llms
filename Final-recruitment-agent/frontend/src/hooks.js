import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

/** Load something once (and again on reload()). Returns { data, error, loading, reload }. */
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const [tick, setTick] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    let cancelled = false
    fnRef
      .current()
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error) => !cancelled && setState({ data: null, error, loading: false }))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }))
    setTick((t) => t + 1)
  }, [])
  return { ...state, reload }
}

/** Follow one run: poll while it is running, stop when it is done or failed. */
export function useRun(runId) {
  const [state, setState] = useState({ data: null, error: null, loading: true })

  useEffect(() => {
    let cancelled = false
    let timer
    let failures = 0

    async function poll() {
      try {
        const data = await api.results(runId)
        if (cancelled) return
        failures = 0
        setState({ data, error: null, loading: false })
        if (data.status === 'running') timer = setTimeout(poll, 700)
      } catch (error) {
        if (cancelled) return
        failures += 1
        // a missing run will not appear by waiting; a flaky connection gets a few retries
        if (error.status === 404 || error.status === 400 || failures >= 5) {
          setState((s) => ({ data: s.data, error, loading: false }))
        } else {
          timer = setTimeout(poll, 1500)
        }
      }
    }
    poll()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [runId])

  return state
}
