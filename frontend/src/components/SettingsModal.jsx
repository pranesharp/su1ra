import { useEffect, useRef, useState } from 'react'
import { ACCENTS, DEFAULT_ACCENT } from '../theme'
import { pullModel, cancelPull } from '../api'

const CTX_STEPS = [0, 512, 1024, 2048, 4096, 8192, 12288, 16384, 24576, 32768, 49152, 65536, 131072]

const SUGGESTED_MODELS = [
  { name: 'ornith-1.5:9b', size: '6.6 GB' },
  { name: 'deepseek-r1:1.5b', size: '1.1 GB' },
  { name: 'llama3.2:3b', size: '2.0 GB' },
  { name: 'qwen2.5:7b', size: '4.7 GB' },
]

function fmtTokens(n) {
  if (!n) return 'default'
  return n >= 1024 ? `${n / 1024}k` : String(n)
}

function nearestIndex(value) {
  let best = 0
  CTX_STEPS.forEach((v, i) => {
    if (Math.abs(v - value) < Math.abs(CTX_STEPS[best] - value)) best = i
  })
  return best
}

export default function SettingsModal({ status, conversation, accent, sandboxTools, onSave, onClose, onModelsChanged }) {
  const [ollamaUrl, setOllamaUrl] = useState(status?.url || 'http://localhost:11434')
  const [systemPrompt, setSystemPrompt] = useState(conversation?.system_prompt || '')
  const [temperature, setTemperature] = useState(conversation?.temperature ?? 0.7)
  const [ctxIndex, setCtxIndex] = useState(nearestIndex(conversation?.context_length || 0))
  const [selectedAccent, setSelectedAccent] = useState(accent || DEFAULT_ACCENT)
  const [sandboxOn, setSandboxOn] = useState(sandboxTools !== false)
  const [pullName, setPullName] = useState('')
  const [pull, setPull] = useState(null)
  const pullCtrl = useRef(null)

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

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const pct = (ctxIndex / (CTX_STEPS.length - 1)) * 100

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Settings</h2>
        <label>
          <span>Ollama server URL</span>
          <input
            type="text"
            value={ollamaUrl}
            onChange={(e) => setOllamaUrl(e.target.value)}
            placeholder="http://localhost:11434"
          />
        </label>
        <label>
          <span>Accent color</span>
          <div className="swatch-grid">
            {ACCENTS.map((a) => (
              <button
                key={a.hex}
                title={a.name}
                className={`swatch${selectedAccent === a.hex ? ' selected' : ''}`}
                style={{ background: a.hex }}
                onClick={() => setSelectedAccent(a.hex)}
              />
            ))}
          </div>
        </label>
        <label>
          <span>System prompt (this chat)</span>
          <textarea
            rows={4}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="You are a helpful assistant."
          />
        </label>
        <label>
          <span>Temperature</span>
          <input
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={temperature}
            onChange={(e) => setTemperature(Number(e.target.value))}
          />
        </label>
        <label>
          <span>Context token length</span>
          <div className="slider-row">
            <input
              type="range"
              min="0"
              max={CTX_STEPS.length - 1}
              step="1"
              className="ctx-slider"
              style={{ background: `linear-gradient(to right, var(--accent) ${pct}%, #26262c ${pct}%)` }}
              value={ctxIndex}
              onChange={(e) => setCtxIndex(Number(e.target.value))}
            />
            <span className="slider-value">{fmtTokens(CTX_STEPS[ctxIndex])}</span>
          </div>
          <div className="slider-scale">
            <span>default</span>
            <span>128k</span>
          </div>
        </label>
        <label className="sandbox-row">
          <input
            type="checkbox"
            checked={sandboxOn}
            onChange={(e) => setSandboxOn(e.target.checked)}
          />
          <span>Sandbox model-run code (no network, isolated filesystem — Linux only)</span>
        </label>
        <div className="pull-section">
          <span>Download a model</span>
          <div className="pull-row">
            <input
              type="text"
              value={pullName}
              onChange={(e) => setPullName(e.target.value)}
              placeholder="model name, e.g. llama3.2:3b"
              disabled={pullActive}
              onKeyDown={(e) => e.key === 'Enter' && startPull(pullName)}
            />
            <button className="btn-accent" disabled={pullActive || !pullName.trim()} onClick={() => startPull(pullName)}>
              Pull
            </button>
          </div>
          <div className="pull-chips">
            {SUGGESTED_MODELS.map((m) => (
              <button key={m.name} className="chip" disabled={pullActive} onClick={() => { setPullName(m.name); startPull(m.name) }}>
                {m.name} · {m.size}
              </button>
            ))}
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
                    {pull.status}… {pull.pct !== null ? `${pull.pct}%` : ''}
                  </span>
                  <button className="btn-ghost" onClick={cancelActivePull}>cancel</button>
                </>
              )}
            </div>
          )}
        </div>
        <div className="modal-actions">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button
            className="btn-accent"
            onClick={() =>
              onSave({
                ollamaUrl: ollamaUrl.trim(),
                systemPrompt,
                temperature,
                contextLength: CTX_STEPS[ctxIndex],
                accent: selectedAccent,
                sandboxTools: sandboxOn,
              })
            }
          >
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
