import { Link, NavLink, Route, Routes } from 'react-router-dom'
import { api } from './api'
import { useAsync } from './hooks'
import Analyze from './pages/Analyze.jsx'
import CheckCv from './pages/CheckCv.jsx'
import Overview from './pages/Overview.jsx'
import Run from './pages/Run.jsx'
import Runs from './pages/Runs.jsx'

function LlmIndicator() {
  const { data, error, loading } = useAsync(api.llmStatus, [])
  if (loading) return <span className="env muted">Checking model…</span>
  if (error) return <span className="env"><span className="dot bad" />API offline</span>
  const ready = data.reachable && data.model_installed
  return (
    <span className="env" title={`Ollama at ${data.host}`}>
      <span className={`dot ${ready ? 'ok' : 'bad'}`} />
      {!data.reachable ? 'Ollama is not running' : ready ? `Ollama ready: ${data.model}` : `Model ${data.model} not installed`}
    </span>
  )
}

function NotFound() {
  return (
    <div className="empty">
      <h2>This page doesn't exist</h2>
      <p className="muted">Check the address, or go back to the overview.</p>
      <Link className="btn" to="/">Go to overview</Link>
    </div>
  )
}

export default function App() {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">Recruitment Agent</Link>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/analyze">New analysis</NavLink>
          <NavLink to="/check-cv">Check one CV</NavLink>
          <NavLink to="/runs">History</NavLink>
        </nav>
        <LlmIndicator />
      </header>
      <main className="page">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/analyze" element={<Analyze />} />
          <Route path="/check-cv" element={<CheckCv />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:runId" element={<Run />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  )
}
