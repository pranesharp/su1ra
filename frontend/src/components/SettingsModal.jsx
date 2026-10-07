import { useEffect, useRef, useState } from 'react'
import { ACCENTS, DEFAULT_ACCENT, DEFAULT_BRIGHTNESS, DEFAULT_CONTRAST, applyBackground, lightBlend } from '../theme'
import { getBundledPrompt, getPromptFile, openPromptInEditor } from '../api'

const CTX_STEPS = [0, 512, 1024, 2048, 4096, 8192, 12288, 16384, 24576, 32768, 49152, 50000, 65536, 131072]

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

function parseCtxText(text) {
  const t = (text || '').trim()
  if (t === '') return 0
  return Math.max(0, parseInt(t, 10) || 0)
}

function CtxField({ label, ctxText, setCtxText, model, hint }) {
  const [nativeCtx, setNativeCtx] = useState(0)

  useEffect(() => {
    let alive = true
    if (model) {
      fetch(`/api/model/ctx?model=${encodeURIComponent(model)}`)
        .then((r) => r.json())
        .then((d) => { if (alive) setNativeCtx(d.context_length || 0) })
        .catch(() => {})
    } else if (alive) {
      setNativeCtx(0)
    }
    return () => { alive = false }
  }, [model])

  const steps = nativeCtx > CTX_STEPS[CTX_STEPS.length - 1] ? [...CTX_STEPS, nativeCtx] : CTX_STEPS
  const maxStep = steps[steps.length - 1]
  // single source of truth: the textbox. empty = default (0). slider always derived from it.
  const savedCtx = parseCtxText(ctxText)
  const sliderIndex = nearestIndex(Math.min(savedCtx, maxStep), steps)
  const ctxWarn = nativeCtx > 0 && savedCtx > nativeCtx

  return (
    <label>
      <span>{label}</span>
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
          placeholder={hint || 'default'}
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
  )
}

function ModelSelect({ label, value, onChange, models }) {
  return (
    <label>
      <span>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: '100%' }}
      >
        <option value="">— select a model —</option>
        {(models || []).map((m) => (
          <option key={m.name} value={m.name}>{m.name}</option>
        ))}
      </select>
      {(!models || models.length === 0) && (
        <p className="ctx-warn">// no models on device — pull one below</p>
      )}
    </label>
  )
}

export default function SettingsModal({ status, conversation, accent, sandboxTools, model, models, loadout, view, onViewChange, bgBrightness, bgContrast, engine, engineVulkan, onSave, onClose, onOpenModels, onServerChanged }) {
  const [ollamaUrl, setOllamaUrl] = useState(status?.url || 'http://localhost:11434')
  const [systemPrompt, setSystemPrompt] = useState(conversation?.system_prompt || '')
  const [temperature, setTemperature] = useState(conversation?.temperature ?? 0.7)
  const [ctxText, setCtxText] = useState(conversation?.context_length ? String(conversation.context_length) : '')
  const [selectedAccent, setSelectedAccent] = useState(accent || DEFAULT_ACCENT)
  const [sandboxOn, setSandboxOn] = useState(sandboxTools !== false)
  const [casualModel, setCasualModel] = useState(loadout?.casualModel || '')
  const [codeModel, setCodeModel] = useState(loadout?.codeModel || '')
  const [casualCtxText, setCasualCtxText] = useState(loadout?.casualCtx ? String(loadout.casualCtx) : '')
  const [codeCtxText, setCodeCtxText] = useState(loadout?.codeCtx ? String(loadout.codeCtx) : '')
  const [casualThink, setCasualThink] = useState(loadout?.casualThink === 'on' ? 'on' : 'off')
  const [bgB, setBgB] = useState(bgBrightness ?? DEFAULT_BRIGHTNESS)
  const [bgC, setBgC] = useState(bgContrast ?? DEFAULT_CONTRAST)
  const [engineSel, setEngineSel] = useState(['auto', 'cpu', 'gpu'].includes(engine) ? engine : 'auto')
  const [vulkanOn, setVulkanOn] = useState(engineVulkan === true)
  const [gpuInfo, setGpuInfo] = useState(null)
  const [restartMsg, setRestartMsg] = useState('')
  const [restartBusy, setRestartBusy] = useState(false)

  async function fetchGpu() {
    try {
      const r = await fetch('/api/gpu')
      setGpuInfo(await r.json())
    } catch { /* detection is best-effort; section stays hidden-ish */ }
  }

  useEffect(() => {
    fetchGpu()
  }, [])
  // refresh the env preview shortly after engine choices land server-side
  useEffect(() => {
    const t = setTimeout(fetchGpu, 700)
    return () => clearTimeout(t)
  }, [engineSel, vulkanOn])

  async function restartServer() {
    setRestartBusy(true)
    setRestartMsg('// restarting server… (loaded models drop)')
    try {
      const r = await fetch('/api/ollama/restart', { method: 'POST' })
      const res = await r.json()
      if (res.ok) {
        setRestartMsg('// server restarted — engine choice is live')
        onServerChanged?.()
      } else {
        setRestartMsg(`// ${res.error || 'restart failed'}`)
      }
    } catch (err) {
      setRestartMsg(`// restart failed: ${err.message}`)
    }
    setRestartBusy(false)
    fetchGpu()
  }
  const [extMsg, setExtMsg] = useState(null)
  const [watching, setWatching] = useState(false)
  const watchMtimeRef = useRef(null)
  const pollRef = useRef(null)

  // No resync-from-props here by design: the modal only mounts after boot
  // (App gates /settings), so mount-time state is DB truth. Re-applying
  // props on every loadout change would clobber in-flight edits and let a
  // stale fetch wipe just-saved values back to empties via autosave.
  function stopWatching() {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = null
    watchMtimeRef.current = null
    setWatching(false)
  }

  useEffect(() => stopWatching, [])


  // live preview while dragging (autosaved, so nothing to revert)
  useEffect(() => {
    applyBackground(bgB, bgC)
  }, [bgB, bgC])

  // autosave: every change persists ~0.5s after the user stops editing.
  // No Save/Cancel buttons — closing flushes any pending save first, so a
  // quick pick-then-close (or jumping to [pull models]) can never lose data.
  const onSaveRef = useRef(onSave)
  useEffect(() => {
    onSaveRef.current = onSave
  })
  function buildPayload() {
    return {
      ollamaUrl: ollamaUrl.trim(),
      systemPrompt,
      temperature,
      contextLength: parseCtxText(ctxText),
      accent: selectedAccent,
      sandboxTools: sandboxOn,
      loadoutCasualThink: casualThink,
      loadoutCasualModel: casualModel,
      loadoutCodeModel: codeModel,
      loadoutCasualCtx: parseCtxText(casualCtxText),
      loadoutCodeCtx: parseCtxText(codeCtxText),
          bgBrightness: bgB,
          bgContrast: bgC,
          engine: engineSel,
          engineVulkan: vulkanOn,
        }
  }
  const buildRef = useRef(buildPayload)
  buildRef.current = buildPayload
  // Immediate save for discrete controls (dropdowns, swatches, toggles,
  // checkboxes): fires the PATCH in ms instead of waiting out the debounce,
  // so closing the app window right after a pick can't lose it — the server
  // thread dies with the window, and an unsent debounce dies with it.
  function commitNow(overrides) {
    setSaveState('saving')
    try {
      const p = onSaveRef.current({ ...buildRef.current(), ...overrides })
      if (p && p.then) p.then(() => setSaveState('saved')).catch(() => setSaveState('error'))
      else setSaveState('saved')
    } catch {
      setSaveState('error')
    }
  }
  const [saveState, setSaveState] = useState('saved')
  const firstRunRef = useRef(true)
  const pendingRef = useRef(false)
  useEffect(() => {
    if (firstRunRef.current) {
      firstRunRef.current = false
      return
    }
    if (!Number.isFinite(temperature)) return
    pendingRef.current = true
    const t = setTimeout(() => {
      pendingRef.current = false
      setSaveState('saving')
      onSaveRef
        .current(buildRef.current())
        .then(() => setSaveState('saved'))
        .catch(() => setSaveState('error'))
    }, 500)
    return () => clearTimeout(t)
  }, [ollamaUrl, systemPrompt, temperature, ctxText, selectedAccent, sandboxOn, casualModel, codeModel, casualCtxText, codeCtxText, casualThink, bgB, bgC, engineSel, vulkanOn])
  // flush-on-unmount: fire-and-forget, no setState (we're unmounting)
  useEffect(
    () => () => {
      if (pendingRef.current) {
        pendingRef.current = false
        try {
          onSaveRef.current(buildRef.current())?.catch(() => {})
        } catch { /* backend down: next open retries from DB truth */ }
      }
    },
    [],
  )

  async function openExternal() {
    try {
      const res = await openPromptInEditor(systemPrompt)
      watchMtimeRef.current = res.mtime
      setWatching(true)
      setExtMsg(`opened in your editor — save the file to update this box (${res.path})`)
      if (pollRef.current) clearInterval(pollRef.current)
      const deadline = Date.now() + 10 * 60 * 1000
      pollRef.current = setInterval(async () => {
        if (Date.now() > deadline) {
          stopWatching()
          return
        }
        try {
          const f = await getPromptFile()
          if (f.mtime && f.mtime !== watchMtimeRef.current) {
            watchMtimeRef.current = f.mtime
            setSystemPrompt(f.content ?? '')
            setExtMsg('// reloaded from external editor')
          }
        } catch { /* keep watching */ }
      }, 1500)
    } catch (err) {
      setExtMsg(`// could not open editor: ${err.message}`)
    }
  }

  async function resetDefault() {
    try {
      const b = await getBundledPrompt()
      if (b.content) {
        setSystemPrompt(b.content)
        setExtMsg('// restored bundled default')
      } else {
        setExtMsg('// no bundled default found')
      }
    } catch (err) {
      setExtMsg(`// reset failed: ${err.message}`)
    }
  }

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])


  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className={`modal ${view === 'split' ? 'modal-split' : 'modal-list'}`} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0 }}>Settings</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="prompt-note" style={{ margin: 0 }}>
              {saveState === 'saving' ? '// saving…' : saveState === 'error' ? '// save failed — retrying' : '// autosaved'}
            </span>
            <button className="btn-ghost" onClick={onClose}>[ close ]</button>
          </div>
        </div>
        <div className="view-toggle">
          <button className={view === 'list' ? 'on' : ''} onClick={() => onViewChange('list')}>[ list ]</button>
          <button className={view === 'split' ? 'on' : ''} onClick={() => onViewChange('split')}>[ split ]</button>
        </div>
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
                onClick={() => { setSelectedAccent(a.hex); commitNow({ accent: a.hex }) }}
              />
            ))}
          </div>
        </label>
        <label>
          <span>Background brightness (0 = vanta black · high = light mode)</span>
          <div className="slider-row">
            <input
              type="range"
              min="0"
              max="150"
              step="1"
              className="ctx-slider"
              style={{ background: `linear-gradient(to right, var(--accent) ${(bgB / 150) * 100}%, #26262c ${(bgB / 150) * 100}%)` }}
              value={bgB}
              onChange={(e) => setBgB(Number(e.target.value))}
            />
            <span className="slider-value">{bgB}{lightBlend(bgB) >= 0.5 ? ' · light' : ''}</span>
          </div>
        </label>
        <label>
          <span>Background contrast</span>
          <div className="slider-row">
            <input
              type="range"
              min="0"
              max="150"
              step="1"
              className="ctx-slider"
              style={{ background: `linear-gradient(to right, var(--accent) ${(bgC / 150) * 100}%, #26262c ${(bgC / 150) * 100}%)` }}
              value={bgC}
              onChange={(e) => setBgC(Number(e.target.value))}
            />
            <span className="slider-value">{bgC}</span>
          </div>
          <div className="slider-scale">
            <span>flat</span>
            <span>punchy</span>
          </div>
        </label>
        <div className="hub-launch">
          <div className="hub-title">Loadout — /code switches between these</div>
          <div className="hub-sub">casual is everyday chat · code is the /code model (ctx bumps to at least 50000)</div>
        </div>
        {view === 'split' ? (
          <div className="loadout-grid">
            <div className="loadout-col">
              <div className="loadout-title"># casual</div>
              <ModelSelect label="Casual model" value={casualModel} onChange={(v) => { setCasualModel(v); commitNow({ loadoutCasualModel: v }) }} models={models} />
              <CtxField label="Casual context" ctxText={casualCtxText} setCtxText={setCasualCtxText} model={casualModel} />
              <label>
                <span>Thinking</span>
                <div className="think-toggle">
                  <button className={`btn-ghost${casualThink === 'on' ? ' on' : ''}`} onClick={() => { setCasualThink('on'); commitNow({ loadoutCasualThink: 'on' }) }}>[ on ]</button>
                  <button className={`btn-ghost${casualThink === 'off' ? ' on' : ''}`} onClick={() => { setCasualThink('off'); commitNow({ loadoutCasualThink: 'off' }) }}>[ off ]</button>
                </div>
              </label>
              <p className="prompt-note">// no need for casual — leave off unless reasoning</p>
            </div>
            <div className="loadout-col">
              <div className="loadout-title"># code</div>
              <ModelSelect label="Code model" value={codeModel} onChange={(v) => { setCodeModel(v); commitNow({ loadoutCodeModel: v }) }} models={models} />
              <CtxField label="Code context" ctxText={codeCtxText} setCtxText={setCodeCtxText} model={codeModel} hint="50000" />
              <p className="prompt-note">// thinking is always on in code mode — coding is better with think · /think off to override</p>
            </div>
          </div>
        ) : (
          <>
            <ModelSelect label="Casual model" value={casualModel} onChange={(v) => { setCasualModel(v); commitNow({ loadoutCasualModel: v }) }} models={models} />
            <CtxField label="Casual context" ctxText={casualCtxText} setCtxText={setCasualCtxText} model={casualModel} />
            <label>
              <span>Thinking (casual)</span>
              <div className="think-toggle">
                <button className={`btn-ghost${casualThink === 'on' ? ' on' : ''}`} onClick={() => { setCasualThink('on'); commitNow({ loadoutCasualThink: 'on' }) }}>[ on ]</button>
                <button className={`btn-ghost${casualThink === 'off' ? ' on' : ''}`} onClick={() => { setCasualThink('off'); commitNow({ loadoutCasualThink: 'off' }) }}>[ off ]</button>
              </div>
            </label>
            <p className="prompt-note">// no need for casual — leave off unless reasoning</p>
            <ModelSelect label="Code model" value={codeModel} onChange={(v) => { setCodeModel(v); commitNow({ loadoutCodeModel: v }) }} models={models} />
            <CtxField label="Code context" ctxText={codeCtxText} setCtxText={setCodeCtxText} model={codeModel} hint="50000" />
            <p className="prompt-note">// thinking is always on in code mode — coding is better with think · /think off to override</p>
          </>
        )}
        <label>
          <span>System prompt (code mode only — ignored in casual chat)</span>
          <textarea
            rows={4}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="You are a helpful assistant."
          />
          <div className="prompt-actions">
            <button className="btn-ghost" onClick={openExternal}>[ edit in external editor ]</button>
            <button className="btn-ghost" onClick={resetDefault}>[ reset to default ]</button>
            {watching && <button className="btn-ghost" onClick={stopWatching}>[ stop watching ]</button>}
          </div>
          {extMsg && <p className="prompt-note">{extMsg}</p>}
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
        <CtxField label="Context token length (this chat)" ctxText={ctxText} setCtxText={setCtxText} model={model} />
        <label className="sandbox-row">
          <input
            type="checkbox"
            checked={sandboxOn}
            onChange={(e) => { setSandboxOn(e.target.checked); commitNow({ sandboxTools: e.target.checked }) }}
          />
          <span>Sandbox model-run code (no network, isolated filesystem — Linux only)</span>
        </label>
        <div className="hub-launch">
          <div className="hub-title">Need another model?</div>
          <div className="hub-sub">Pull from the Ollama library — e.g. qwen3, gemma3, deepseek-r1</div>
          <button className="btn-accent hub-cta" onClick={onOpenModels}>[ pull models ]</button>
        </div>
        <div className="hub-launch">
          <div className="hub-title">Engine — CPU or GPU for the Ollama server</div>
          <div className="hub-sub">applies when Su1ra starts the server — restart below to take effect</div>
        </div>
        <label>
          <span>Engine</span>
          <div className="think-toggle">
            {[['auto', '[ auto ]'], ['cpu', '[ cpu only ]'], ['gpu', '[ gpu ]']].map(([v, label]) => (
              <button
                key={v}
                className={`btn-ghost${engineSel === v ? ' on' : ''}`}
                onClick={() => { setEngineSel(v); commitNow({ engine: v }) }}
              >
                {label}
              </button>
            ))}
          </div>
        </label>
        {engineSel === 'gpu' && (
          <div>
            {gpuInfo ? (
              <>
                <p className="prompt-note">
                  // NVIDIA CUDA: {gpuInfo.nvidia ? (gpuInfo.nvidia_names.join('; ') || 'detected') : 'not detected'}
                </p>
                <p className="prompt-note">
                  // Vulkan loader: {gpuInfo.vulkan ? 'present' : 'missing — install GPU drivers'}
                  {gpuInfo.intel ? ` · Intel: ${gpuInfo.intel}` : ''}
                  {gpuInfo.amd ? ` · AMD: ${gpuInfo.amd}` : ''}
                </p>
                {gpuInfo.nvidia ? (
                  <p className="prompt-note">// CUDA card found — Ollama uses it automatically, nothing to force</p>
                ) : gpuInfo.vulkan ? (
                  <label className="sandbox-row">
                    <input
                      type="checkbox"
                      checked={vulkanOn}
                      onChange={(e) => { setVulkanOn(e.target.checked); commitNow({ engineVulkan: e.target.checked }) }}
                    />
                    <span>Use Intel / other GPU via Vulkan (experimental — MoE models may crash; CPU stays the fallback)</span>
                  </label>
                ) : (
                  <p className="prompt-note">// no GPU backend visible — CPU it is (install GPU drivers, then re-open settings)</p>
                )}
              </>
            ) : (
              <p className="prompt-note">// detecting GPUs…</p>
            )}
          </div>
        )}
        {engineSel === 'cpu' && (
          <p className="prompt-note">// hides every GPU backend — pure CPU inference after restart</p>
        )}
        {gpuInfo && gpuInfo.env && Object.keys(gpuInfo.env).length > 0 && (
          <p className="prompt-note">
            // server env on restart: {Object.entries(gpuInfo.env).map(([k, v]) => `${k}=${v}`).join(' ')}
          </p>
        )}
        <div className="prompt-actions">
          <button className="btn-ghost" onClick={restartServer} disabled={restartBusy}>[ restart server ]</button>
          {restartMsg && <span className="prompt-note" style={{ margin: 0 }}>{restartMsg}</span>}
        </div>
      </div>
    </div>
  )
}
