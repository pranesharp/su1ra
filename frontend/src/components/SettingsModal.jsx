import { useEffect, useState } from 'react'
import { ACCENTS, DEFAULT_ACCENT } from '../theme'

const CTX_STEPS = [0, 512, 1024, 2048, 4096, 8192, 12288, 16384, 24576, 32768, 49152, 65536, 131072]

function fmtTokens(n) {
  if (!n) return 'default'
  return n >= 1024 ? `${n / 1024}k` : String(n)
}

function nearestIndex(value, list) {
  let best = 0
  list.forEach((v, i) => {
    if (Math.abs(v - value) < Math.abs(list[best] - value)) best = i
  })
  return best
}

export default function SettingsModal({ status, conversation, accent, sandboxTools, model, onSave, onClose, onOpenModels }) {
  const [ollamaUrl, setOllamaUrl] = useState(status?.url || 'http://localhost:11434')
  const [systemPrompt, setSystemPrompt] = useState(conversation?.system_prompt || '')
  const [temperature, setTemperature] = useState(conversation?.temperature ?? 0.7)
  const [ctxText, setCtxText] = useState(conversation?.context_length ? String(conversation.context_length) : '')
  const [nativeCtx, setNativeCtx] = useState(0)
  const [selectedAccent, setSelectedAccent] = useState(accent || DEFAULT_ACCENT)
  const [sandboxOn, setSandboxOn] = useState(sandboxTools !== false)

  useEffect(() => {
    let alive = true
    if (model) {
      fetch(`/api/model/ctx?model=${encodeURIComponent(model)}`)
        .then((r) => r.json())
        .then((d) => { if (alive) setNativeCtx(d.context_length || 0) })
        .catch(() => {})
    }
    return () => { alive = false }
  }, [model])

  const steps = nativeCtx > CTX_STEPS[CTX_STEPS.length - 1] ? [...CTX_STEPS, nativeCtx] : CTX_STEPS
  const maxStep = steps[steps.length - 1]
  // single source of truth: the textbox. empty = default (0). slider always derived from it.
  const savedCtx = ctxText.trim() === '' ? 0 : Math.max(0, parseInt(ctxText, 10) || 0)
  const sliderIndex = nearestIndex(Math.min(savedCtx, maxStep), steps)
  const ctxWarn = nativeCtx > 0 && savedCtx > nativeCtx

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])


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
              max={steps.length - 1}
              step="1"
              className="ctx-slider"
              style={{ background: `linear-gradient(to right, var(--accent) ${(sliderIndex / (steps.length - 1)) * 100}%, #26262c ${(sliderIndex / (steps.length - 1)) * 100}%)` }}
              value={sliderIndex}
              onChange={(e) => {
                const v = steps[Number(e.target.value)] || 0
                setCtxText(v ? String(v) : '')
              }}
            />
            <input
              type="text"
              inputMode="numeric"
              className="ctx-input"
              value={ctxText}
              placeholder="default"
              onChange={(e) => {
                const digits = e.target.value.replace(/[^0-9]/g, '').slice(0, 7)
                setCtxText(digits)
              }}
            />
          </div>
          <div className="slider-scale">
            <span>default</span>
            <span>{nativeCtx > 0 ? `model max ${fmtTokens(nativeCtx)}` : `${fmtTokens(steps[steps.length - 1])}`}</span>
          </div>
          {ctxWarn && (
            <p className="ctx-warn">// above {model}'s trained window ({fmtTokens(nativeCtx)}) — quality will degrade</p>
          )}
        </label>
        <label className="sandbox-row">
          <input
            type="checkbox"
            checked={sandboxOn}
            onChange={(e) => setSandboxOn(e.target.checked)}
          />
          <span>Sandbox model-run code (no network, isolated filesystem — Linux only)</span>
        </label>
        <div className="hub-launch">
          <span>Need another model?</span>
          <button className="btn-ghost" onClick={onOpenModels}>[ pull models ]</button>
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
                contextLength: savedCtx,
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
