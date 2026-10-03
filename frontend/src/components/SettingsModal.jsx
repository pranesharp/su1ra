import { useEffect, useState } from 'react'
import { ACCENTS, DEFAULT_ACCENT } from '../theme'

const CTX_STEPS = [0, 512, 1024, 2048, 4096, 8192, 12288, 16384, 24576, 32768, 49152, 65536, 131072]

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

export default function SettingsModal({ status, conversation, accent, sandboxTools, onSave, onClose }) {
  const [ollamaUrl, setOllamaUrl] = useState(status?.url || 'http://localhost:11434')
  const [systemPrompt, setSystemPrompt] = useState(conversation?.system_prompt || '')
  const [temperature, setTemperature] = useState(conversation?.temperature ?? 0.7)
  const [ctxIndex, setCtxIndex] = useState(nearestIndex(conversation?.context_length || 0))
  const [selectedAccent, setSelectedAccent] = useState(accent || DEFAULT_ACCENT)
  const [sandboxOn, setSandboxOn] = useState(sandboxTools !== false)

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
