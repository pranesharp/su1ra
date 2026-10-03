import { useEffect, useRef, useState } from 'react'

export default function OllamaSetup({ onResolved }) {
  const [state, setState] = useState(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const ctrl = useRef(null)

  async function check() {
    try {
      const r = await fetch('/api/ollama/state')
      setState(await r.json())
    } catch {
      setState(null)
    }
  }

  useEffect(() => {
    check()
    const t = setInterval(check, 8000)
    return () => {
      clearInterval(t)
      ctrl.current?.abort()
    }
  }, [])

  async function startServer() {
    setBusy(true)
    setError('')
    try {
      const r = await fetch('/api/ollama/start', { method: 'POST' })
      const res = await r.json()
      if (res.ok) {
        setDone(true)
        onResolved?.()
      } else {
        setError(res.error || 'could not start ollama')
      }
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  async function install() {
    setBusy(true)
    setError('')
    setProgress({ pct: 0 })
    ctrl.current = new AbortController()
    try {
      const res = await fetch('/api/ollama/install', { method: 'POST', signal: ctrl.current.signal })
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let nl
        while ((nl = buf.indexOf('\n')) >= 0) {
          const evt = JSON.parse(buf.slice(0, nl))
          buf = buf.slice(nl + 1)
          if (evt.error) {
            setError(evt.error)
            setProgress(null)
          } else if (evt.ok) {
            setProgress(null)
            setDone(true)
            onResolved?.()
          } else if (evt.pct !== undefined) {
            setProgress({ pct: evt.pct, got: evt.got, total: evt.total })
          } else if (evt.status) {
            setProgress((p) => ({ ...(p || {}), phase: evt.status, pct: evt.status === 'extracting' || evt.status === 'starting server' ? null : p?.pct }))
          }
        }
      }
    } catch (e) {
      if (!ctrl.current.signal.aborted) setError(e.message)
    }
    setBusy(false)
  }

  if (done || (state && state.server)) return null
  if (!state) return null

  return (
    <div className="setup-box">
      {error ? (
        <>
          <p className="setup-err">// {error}</p>
          {state.binary && (
            <button className="btn-accent" onClick={startServer} disabled={busy}>try again</button>
          )}
        </>
      ) : done ? null : state.binary ? (
        <>
          <p>// ollama is installed but not running</p>
          <button className="btn-accent" onClick={startServer} disabled={busy}>
            {busy ? 'starting…' : '[ start ollama ]'}
          </button>
        </>
      ) : state.install_supported ? (
        <>
          <p>// no ollama detected — the engine that runs models locally, right on this machine</p>
          {progress ? (
            progress.phase ? (
              <p className="setup-phase">// {progress.phase}…</p>
            ) : (
              <div className="setup-progress">
                <div className="pull-bar">
                  <div className="pull-fill" style={{ width: `${progress.pct}%` }} />
                </div>
                <span className="pull-pct">downloading ollama… {progress.pct}%</span>
              </div>
            )
          ) : (
            <button className="btn-accent" onClick={install} disabled={busy}>[ install ollama ]</button>
          )}
        </>
      ) : (
        <p>// no ollama detected — install it from ollama.com/download, then restart Su1ra</p>
      )}
    </div>
  )
}
