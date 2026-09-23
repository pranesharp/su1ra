import { useEffect, useState } from 'react'

export default function SettingsModal({ status, conversation, onSave, onClose }) {
  const [ollamaUrl, setOllamaUrl] = useState(status?.url || 'http://localhost:11434')
  const [systemPrompt, setSystemPrompt] = useState(conversation?.system_prompt || '')
  const [temperature, setTemperature] = useState(conversation?.temperature ?? 0.7)
  const [contextLength, setContextLength] = useState(
    conversation?.context_length ? String(conversation.context_length) : '',
  )

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
          <span>Context token length (blank = ollama default)</span>
          <input
            type="number"
            min="0"
            step="512"
            value={contextLength}
            onChange={(e) => setContextLength(e.target.value)}
            placeholder="4096"
          />
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
                contextLength: Math.max(0, Math.round(Number(contextLength) || 0)),
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
