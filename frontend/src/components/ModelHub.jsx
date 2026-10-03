import { useEffect, useRef, useState } from 'react'
import { pullModel, cancelPull } from '../api'

const CATALOG = [
  { name: 'ornith-1.5:9b', params: '9B', size: '6.6 GB', caps: ['tools', 'thinking', 'vision'] },
  { name: 'deepseek-r1:1.5b', params: '1.8B', size: '1.1 GB', caps: ['tools', 'thinking'] },
  { name: 'llama3.2:3b', params: '3B', size: '2.0 GB', caps: ['tools'] },
  { name: 'qwen2.5:7b', params: '7.6B', size: '4.7 GB', caps: ['tools'] },
  { name: 'qwen2.5-coder:7b', params: '7.6B', size: '4.7 GB', caps: ['tools', 'code'] },
  { name: 'llama3.1:8b', params: '8B', size: '4.9 GB', caps: ['tools'] },
  { name: 'gemma3:4b', params: '4.3B', size: '3.3 GB', caps: ['tools', 'vision'] },
  { name: 'mistral:7b', params: '7.2B', size: '4.4 GB', caps: ['tools'] },
]

export default function ModelHub({ models, onModelsChanged, onClose }) {
  const [pullName, setPullName] = useState('')
  const [pull, setPull] = useState(null)
  const pullCtrl = useRef(null)

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const installed = new Set(models.map((m) => m.name))
  const pullActive = pull && !pull.done && !pull.err

  async function startPull(name) {
    name = (name || '').trim()
    if (!name || pullActive) return
    const ctrl = new AbortController()
    pullCtrl.current = ctrl
    setPull({ name, pct: null, status: 'starting', done: false, err: '' })
    try {
      await pullModel(
        name,
        (evt) => {
          if (evt.error) setPull((p) => (p ? { ...p, err: evt.error } : p))
          else if (evt.status === 'success') setPull((p) => (p ? { ...p, done: true, pct: 100, status: 'done' } : p))
          else if (evt.pct !== undefined) setPull((p) => (p ? { ...p, pct: evt.pct, status: 'pulling' } : p))
          else setPull((p) => (p ? { ...p, status: evt.status } : p))
        },
        ctrl.signal,
      )
      setPull((p) => (p && !p.err ? { ...p, done: true, pct: 100, status: 'done' } : p))
      onModelsChanged?.()
    } catch (err) {
      if (!ctrl.signal.aborted) setPull((p) => (p ? { ...p, err: err.message } : p))
    } finally {
      pullCtrl.current = null
    }
  }

  function cancelActivePull() {
    if (pull?.name) cancelPull(pull.name)
    pullCtrl.current?.abort()
    setPull(null)
  }

  function fmtPct(p) {
    return p === null || p === undefined ? '' : ` ${p}%`
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>model hub</h2>
        <div className="pull-section">
          <div className="pull-row">
            <input
              type="text"
              value={pullName}
              onChange={(e) => setPullName(e.target.value)}
              placeholder="any ollama model name, e.g. llama3.2:3b"
              disabled={pullActive}
              onKeyDown={(e) => e.key === 'Enter' && startPull(pullName)}
            />
            <button className="btn-accent" disabled={pullActive || !pullName.trim()} onClick={() => startPull(pullName)}>
              Pull
            </button>
          </div>
          {pull && (
            <div className="pull-progress">
              {pull.err ? (
                <span className="pull-err">// pull failed: {pull.err}</span>
              ) : pull.done ? (
                <span>// pulled {pull.name} — it is now in /models</span>
              ) : (
                <>
                  <div className="pull-bar">
                    <div className="pull-fill" style={{ width: `${pull.pct ?? 0}%` }} />
                  </div>
                  <span className="pull-pct">
                    pulling {pull.name} — {pull.status}…{fmtPct(pull.pct)}
                  </span>
                  <button className="btn-ghost" onClick={cancelActivePull}>cancel</button>
                </>
              )}
            </div>
          )}
        </div>
        <div className="hub-list">
          {CATALOG.map((m) => {
            const isInstalled = installed.has(m.name)
            const isPulling = pullActive && pull.name === m.name
            return (
              <div key={m.name} className={`hub-row${isPulling ? ' pulling' : ''}`}>
                <div className="hub-main">
                  <span className="hub-name">{m.name}</span>
                  <span className="hub-specs">{m.params} · {m.size} · {m.caps.join(', ')}</span>
                </div>
                {isPulling ? (
                  <div className="pull-bar hub-bar">
                    <div className="pull-fill" style={{ width: `${pull.pct ?? 0}%` }} />
                  </div>
                ) : (
                  <button
                    className="btn-ghost"
                    disabled={pullActive}
                    onClick={() => { setPullName(m.name); startPull(m.name) }}
                  >
                    {isInstalled ? '[ installed ]' : '[ pull ]'}
                  </button>
                )}
              </div>
            )
          })}
        </div>
        <p className="hub-hint">// catalog is a starter set — any model on ollama.com works by name above</p>
        <div className="modal-actions">
          <button className="btn-accent" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  )
}
