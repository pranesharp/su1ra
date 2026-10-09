import { useEffect, useRef, useState } from 'react'

export default function OllamaSetup({ onResolved }) {
  const [state, setState] = useState(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  // Troubleshooting bridge: after a failed install we don't dump the user
  // straight onto an error + button. We pause on an animated "please wait,
  // troubleshooting…" state, re-check whether the binary actually landed
  // (extraction often succeeded — only cleanup failed), and auto-retry once.
  const [trouble, setTrouble] = useState(false)
  const ctrl = useRef(null)

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  // Rising edge: if the server comes up on its own (e.g. the app boot
  // thread finishes starting it after this box first rendered), tell App
  // so the [offline] badge flips without any click. Otherwise the header
  // lies stale until the next manual action.
  const wasServer = useRef(null)

  async function check() {
    try {
      const r = await fetch('/api/ollama/state')
      const st = await r.json()
      setState(st)
      // Fire on null→true too (first poll already seeing a running server
      // is the common case — strict false→true missed it and the badge
      // lied stale). refreshStatus is idempotent, extra calls are harmless.
      if (st.server && wasServer.current !== true) onResolved?.()
      wasServer.current = st.server
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

  async function install(auto = false) {
    setBusy(true)
    if (!auto) setError('')
    setProgress({ pct: 0 })
    // Fresh controller per attempt — a stale/aborted signal must never be
    // able to silently swallow a new attempt (that wedges the UI at 0%).
    ctrl.current = new AbortController()
    const signal = ctrl.current.signal
    let failed = null
    let sawEvent = false
    let watchdogFired = false
    const watchdog = setTimeout(() => {
      if (!sawEvent && !signal.aborted) {
        watchdogFired = true
        try { ctrl.current.abort() } catch { /* handled below */ }
      }
    }, 25000)
    try {
      const res = await fetch('/api/ollama/install', { method: 'POST', signal })
      if (!res.ok || !res.body) {
        let detail = `HTTP ${res.status}`
        try {
          const body = await res.json()
          detail = body.detail || JSON.stringify(body).slice(0, 200)
        } catch {
          try { detail = (await res.text()).slice(0, 200) || detail } catch { /* keep status */ }
        }
        failed = `install request failed: ${detail}`
      } else {
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
            sawEvent = true
            if (evt.error) {
              failed = evt.error
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
      }
    } catch (e) {
      if (watchdogFired) {
        failed = failed || 'installer sent nothing for 25s — connection or server wedged, try again'
      } else if (!signal.aborted) {
        failed = failed || e.message
      } else {
        failed = failed || 'install interrupted — click try again'
      }
    } finally {
      clearTimeout(watchdog)
    }
    setBusy(false)
    if (failed && !auto) {
      // First failure → troubleshooting bridge (auto single retry inside).
      troubleshoot(failed)
    } else if (failed) {
      setError(failed)
    }
  }

  async function troubleshoot(firstErr) {
    setTrouble(true)
    setProgress(null)
    await sleep(2500)
    // Did the binary actually land? Extraction usually succeeded and only
    // cleanup tripped — in that case skip re-downloading entirely.
    try {
      const r = await fetch('/api/ollama/state')
      const st = await r.json()
      setState(st)
      if (st.binary) {
        setTrouble(false)
        setError('')
        return
      }
    } catch { /* fall through to the retry */ }
    // One automatic retry before asking the user to click anything.
    await install(true)
    setTrouble(false)
  }

  const [dismissed, setDismissed] = useState(false)
  if (dismissed) return null
  // After a fresh install/start through this box, show next steps instead of
  // vanishing — a new user otherwise lands on an empty chat with no model.
  // (Server already running at launch → null as before, no nagging.)
  if (done) {
    return (
      <div className="setup-box">
        <p className="setup-hint">// ollama is ready — next:</p>
        <p>// 1. pull a model in /settings ([ pull models ])</p>
        <p>// 2. pick it in chat with /models &lt;name&gt;</p>
        <p>// 3. /code for coding, /modes to see where you are</p>
        <button className="btn-accent" onClick={() => setDismissed(true)}>[ start chatting ]</button>
      </div>
    )
  }
  if ((state && state.server)) return null
  if (!state) return null

  return (
    <div className="setup-box">
      {trouble ? (
        <p className="setup-trouble">// please wait, troubleshooting…<span className="cursor" /></p>
      ) : error ? (
        <>
          <p className="setup-err">// {error}</p>
          {state.binary ? (
            <button className="btn-accent" onClick={startServer} disabled={busy}>try again — it usually works</button>
          ) : (
            <button className="btn-accent" onClick={() => install(false)} disabled={busy}>try again — it usually works</button>
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
                <span className="pull-pct">
                  downloading ollama…{' '}
                  {progress.got && progress.total
                    ? `${(progress.got / 1048576).toFixed(1)} / ${(progress.total / 1048576).toFixed(0)} MB (${progress.pct}%)`
                    : `${progress.pct}%`}
                </span>
              </div>
            )
          ) : (
            <>
              <button className="btn-accent" onClick={install} disabled={busy}>[ install ollama ]</button>
              <p className="setup-hint">// troubled installs fix themselves once automatically — then select your models in settings, then restart the app</p>
            </>
          )}
        </>
      ) : (
        <p>// no ollama detected — install it from ollama.com/download, then restart Su1ra</p>
      )}
    </div>
  )
}
