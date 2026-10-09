import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api'
import { applyAccent, applyBackground, DEFAULT_ACCENT, DEFAULT_BRIGHTNESS, DEFAULT_CONTRAST, readInjectedTheme } from './theme'
import ChatView, { splitThinking } from './components/ChatView.jsx'
import Composer from './components/Composer.jsx'
import Logo from './components/Logo.jsx'
import SettingsModal from './components/SettingsModal.jsx'
import ModelHub from './components/ModelHub.jsx'
import IdePane from './components/IdePane.jsx'
import WindowControls from './components/TitleBar.jsx'
import ArtifactPane from './components/ArtifactPane.jsx'
import { copyText } from './clip'

const COMMANDS = [
  { cmd: '/help', desc: 'show available commands' },
  { cmd: '/models', desc: 'list models — /models <name|n> to select, /models pull <name> to download, /models rm <name|n> to delete, /models get [query] to browse' },
  { cmd: '/newchat', desc: 'start a new conversation' },
  { cmd: '/chats', desc: 'list chats — /chats <n|id> to open' },
  { cmd: '/delchat', desc: 'delete a chat — /delchat <n|id>, or /delchat all to wipe all history' },
  { cmd: '/clear', desc: 'clear the current chat (messages only, keeps the chat + settings)' },
  { cmd: '/settings', desc: 'open settings' },
  { cmd: '/eject', desc: 'shut down the ollama server instantly' },
  { cmd: '/connect', desc: 'start / reconnect the ollama server' },
  { cmd: '/stats', desc: 'toggle per-reply performance stats' },
  { cmd: '/think', desc: 'thinking — /think, /think on|off|auto (this chat, persisted)' },
  { cmd: '/code', desc: 'toggle code mode — switches to the code loadout model/ctx, unloads the casual model; /code <msg> arms one message' },
  { cmd: '/casual', desc: 'switch to casual mode — everyday chat model, unloads the code model, tools off' },
  { cmd: '/modes', desc: 'show current mode — casual/code plus model, ctx, think, tools' },
  { cmd: '/ide', desc: 'toggle the python ide pane' },
  { cmd: '/mkdir', desc: 'new project folder in the workspace — /mkdir <name>' },
  { cmd: '/cd', desc: 'switch active project — /cd <name>, or bare /cd to show root + project' },
]

const STARTER_CODE = `# scratch — runs in ~/.local/share/su1ra/scratch
print("hello from su1ra")

for i in range(3):
    print(f"tick {i}")`

export default function App() {
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [models, setModels] = useState([])
  const [status, setStatus] = useState(null)
  const refreshStatus = useCallback(async () => {
    // Status AND models: both are fetched once at boot (often while the
    // server is still coming up), so every refresh reloads both — otherwise
    // the loadout dropdowns lie stuck on "no models on device".
    try {
      setStatus(await api.getStatus())
    } catch { /* backend hiccup: keep last known */ }
    try {
      const r = await api.getModels()
      setModels(r.models)
    } catch { /* same: keep last known list */ }
  }, [])
  const [selectedModel, setSelectedModel] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [modelHubOpen, setModelHubOpen] = useState(false)
  // First paint uses the theme the backend stamped into index.html
  // (window.__SU1RA_THEME__) — no flash of the hardcoded defaults.
  // useState initializer form so it reads exactly once.
  const [accent, setAccent] = useState(() => readInjectedTheme().accent || DEFAULT_ACCENT)
  const [bgBrightness, setBgBrightness] = useState(() => readInjectedTheme().bgBrightness ?? DEFAULT_BRIGHTNESS)
  const [bgContrast, setBgContrast] = useState(() => readInjectedTheme().bgContrast ?? DEFAULT_CONTRAST)
  const [showStats, setShowStats] = useState(false)
  const [ideOpen, setIdeOpen] = useState(false)
  const [ideWidth, setIdeWidth] = useState(460)
  const [ideCode, setIdeCode] = useState(STARTER_CODE)
  const [ideOutput, setIdeOutput] = useState({ text: '', exitCode: null })
  const [artifact, setArtifact] = useState(null)
  const [artifactTab, setArtifactTab] = useState('preview')
  const [artifactPath, setArtifactPath] = useState(null)
  const [workspace, setWorkspace] = useState({ root: '', project: '' })
  const [codeArmed, setCodeArmed] = useState(false)
  const [sandboxTools, setSandboxTools] = useState(true)
  const [loadout, setLoadout] = useState({ casualModel: '', codeModel: '', casualCtx: 0, codeCtx: 0, casualThink: 'off' })
  const [engine, setEngine] = useState('auto')
  const [engineVulkan, setEngineVulkan] = useState(false)
  const [settingsView, setSettingsView] = useState('split')
  const abortRef = useRef(null)
  const modelPullRef = useRef(null)
  const pendingToolRef = useRef(null)
  // Deltas/stats must target the streaming assistant message BY ID, never by
  // position: mid-stream system lines (background unload notes, tool status)
  // would otherwise hijack following tokens into the wrong bubble and even
  // break think-tag parsing with glued text.
  const streamTargetRef = useRef(null)
  const ideRunSeenRef = useRef(null)
  const [runSignal, setRunSignal] = useState(0)
  const idRef = useRef(1000)
  const bootedRef = useRef(false)
  const chatDefaultsRef = useRef({ system_prompt: '', temperature: 0.7, context_length: 0, think: null })
  const widthRef = useRef(460)
  const moveRef = useRef(null)
  const upRef = useRef(null)
  const [ctxMenu, setCtxMenu] = useState(null)
  const ctxTimerRef = useRef(null)

  useEffect(() => {
    applyAccent(accent)
  }, [accent])

  useEffect(() => {
    applyBackground(bgBrightness, bgContrast)
  }, [bgBrightness, bgContrast])

  // Right-button text selection + right-click copy menu. Chromium does not
  // start selections with the right button, and the desktop shell may not
  // offer a native context menu — so: right-drag extends a selection from
  // the press point, and right-clicking selected text shows [ copy ].
  // Inputs, textareas, the xterm terminal and iframes keep native behavior.
  useEffect(() => {
    const skip = (t) => t && t.closest && t.closest('input, textarea, .xterm, iframe')
    let anchor = null
    let sx = 0
    let sy = 0
    let moved = false
    let suppressNext = false

    function caretAt(x, y) {
      try {
        const r = document.caretRangeFromPoint && document.caretRangeFromPoint(x, y)
        return r ? { node: r.startContainer, offset: r.startOffset } : null
      } catch {
        return null
      }
    }

    function extendSelection(x, y) {
      const cur = caretAt(x, y)
      if (!anchor || !cur) return
      const sel = window.getSelection()
      if (!sel) return
      try {
        const range = document.createRange()
        range.setStart(anchor.node, anchor.offset)
        range.setEnd(cur.node, cur.offset)
        if (range.collapsed) {
          range.setStart(cur.node, cur.offset)
          range.setEnd(anchor.node, anchor.offset)
        }
        sel.removeAllRanges()
        sel.addRange(range)
      } catch { /* anchor node detached mid-drag */ }
    }

    function openMenu(x, y) {
      if (ctxTimerRef.current) clearTimeout(ctxTimerRef.current)
      setCtxMenu({
        x: Math.min(x, window.innerWidth - 150),
        y: Math.min(y, window.innerHeight - 60),
        done: null,
      })
    }

    function onDown(e) {
      if (e.button !== 2 || skip(e.target)) {
        if (e.button === 0 && !e.target.closest('.ctx-menu')) setCtxMenu(null)
        return
      }
      sx = e.clientX
      sy = e.clientY
      moved = false
      anchor = caretAt(sx, sy)
    }

    function onMove(e) {
      if (!(e.buttons & 2) || !anchor) return
      if (Math.hypot(e.clientX - sx, e.clientY - sy) < 4) return
      moved = true
      extendSelection(e.clientX, e.clientY)
    }

    function onUp(e) {
      if (e.button === 2 && moved) suppressNext = true
      anchor = e.button === 2 ? null : anchor
    }

    function onCtx(e) {
      if (skip(e.target)) return // native menu for fields / terminal
      const text = window.getSelection ? String(window.getSelection()) : ''
      if (suppressNext) {
        suppressNext = false
        e.preventDefault()
        e.stopPropagation()
        if (text) openMenu(e.clientX, e.clientY)
        return
      }
      if (text) {
        e.preventDefault()
        e.stopPropagation()
        openMenu(e.clientX, e.clientY)
      }
      // no selection: leave the native menu alone
    }

    function onKey(e) {
      if (e.key === 'Escape') setCtxMenu(null)
    }

    document.addEventListener('mousedown', onDown)
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    document.addEventListener('contextmenu', onCtx, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.removeEventListener('contextmenu', onCtx, true)
      document.removeEventListener('keydown', onKey)
      if (ctxTimerRef.current) clearTimeout(ctxTimerRef.current)
    }
  }, [])

  async function copySelection() {
    const text = window.getSelection ? String(window.getSelection()) : ''
    const ok = await copyText(text)
    setCtxMenu((m) => (m ? { ...m, done: ok } : m))
    if (ctxTimerRef.current) clearTimeout(ctxTimerRef.current)
    ctxTimerRef.current = setTimeout(() => setCtxMenu(null), 900)
  }

  useEffect(() => {
    async function boot() {
      const [statusRes, modelsRes, convsRes, settingsRes] = await Promise.all([
        api.getStatus(),
        api.getModels(),
        api.getConversations(),
        api.getSettings(),
      ])
      setStatus(statusRes)
      setAccent(settingsRes.accent || DEFAULT_ACCENT)
      // ?? — 0 is a valid vanta-black value, must not fall back to 100
      setBgBrightness(settingsRes.bg_brightness ?? DEFAULT_BRIGHTNESS)
      setBgContrast(settingsRes.bg_contrast ?? DEFAULT_CONTRAST)
      // Loadout contexts are the persisted defaults (survive restart).
      // Casual falls back to the legacy default for users upgrading.
      const casualCtx = settingsRes.loadout_casual_ctx || settingsRes.default_context_length || 0
      const codeCtx = settingsRes.loadout_code_ctx || 0
      // casual think: loadout toggle wins, legacy default_think migrates, fresh installs get off
      const casualThink = (settingsRes.loadout_casual_think || settingsRes.default_think) === 'on' ? 'on' : 'off'
      setLoadout({
        casualModel: settingsRes.loadout_casual_model || '',
        codeModel: settingsRes.loadout_code_model || '',
        casualCtx,
        codeCtx,
        casualThink,
      })
      setSettingsView(settingsRes.settings_view === 'list' ? 'list' : 'split')
      setEngine(['auto', 'cpu', 'gpu'].includes(settingsRes.engine) ? settingsRes.engine : 'auto')
      setEngineVulkan(settingsRes.engine_vulkan === true)
      chatDefaultsRef.current = {
        system_prompt: settingsRes.default_system_prompt || '',
        temperature: typeof settingsRes.default_temperature === 'number' ? settingsRes.default_temperature : 0.7,
        context_length: casualCtx,
        // unset per chat: at send time a null falls back to the loadout
        // (casual toggle) or forced-on (code mode). A stored 'off' would
        // shadow code mode's think-on, so only /think writes it explicitly.
        think: null,
      }
      setShowStats(settingsRes.show_stats === true)
      setIdeOpen(settingsRes.ide_open === true)
      setIdeWidth(typeof settingsRes.ide_width === 'number' ? settingsRes.ide_width : 460)
      setSandboxTools(settingsRes.sandbox_tools !== false)
      setWorkspace({ root: settingsRes.workspace_root || '', project: settingsRes.active_project || '' })
      setModels(modelsRes.models)
      setConversations(convsRes.conversations)
      // Startup is always a fresh casual desk: no chat selected (history stays
      // in /chats), casual loadout preselected. The first send lazily creates
      // the chat, so nothing from a previous session leaks into the new one.
      const casualModel = settingsRes.loadout_casual_model || ''
      setCodeArmed(false)
      setActiveId(null)
      setMessages([])
      if (casualModel) setSelectedModel(casualModel)
      bootedRef.current = true
    }
    boot()
  }, [])

  useEffect(() => {
    widthRef.current = ideWidth
  }, [ideWidth])

  useEffect(() => {
    return () => {
      if (moveRef.current) window.removeEventListener('mousemove', moveRef.current)
      if (upRef.current) window.removeEventListener('mouseup', upRef.current)
    }
  }, [])

  const activeConversation = conversations.find((c) => c.id === activeId) || null
  const blocked = streaming

  function pushSystem(content, role = 'system') {
    setMessages((prev) => [...prev, { id: ++idRef.current, role, content }])
  }

  async function selectConversation(id) {
    if (blocked) return
    const detail = await api.getConversation(id)
    if (!detail) return
    setActiveId(detail.conversation.id)
    setMessages(detail.messages)
    setSelectedModel(detail.conversation.model || '')
  }

  async function newChat() {
    if (blocked) return
    const conversation = await api.createConversation({ model: selectedModel, ...chatDefaultsRef.current })
    setConversations((prev) => [conversation, ...prev])
    setActiveId(conversation.id)
    setMessages([])
    return conversation
  }

  async function deleteConversation(id) {
    if (blocked) return
    await api.deleteConversation(id)
    setConversations((prev) => prev.filter((c) => c.id !== id))
    if (id === activeId) {
      setActiveId(null)
      setMessages([])
    }
  }

  async function changeModel(name) {
    setSelectedModel(name)
    if (activeConversation) {
      const updated = await api.updateConversation(activeConversation.id, { model: name })
      if (updated) {
        setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
      }
    }
  }

  // Unload the outgoing model on a mode switch only (never on /newchat or
  // boot): if the loadouts name different models, drop the old one first so
  // a 16GB box doesn't carry both resident. Best-effort — the switch
  // proceeds even when the unload fails.
  async function unloadIfSwitching(oldName, newName) {
    if (!oldName || !newName || oldName === newName) return false
    try {
      const res = await api.unloadModel(oldName)
      return res && res.unloaded === true
    } catch {
      return false
    }
  }

  // Fire-and-forget model eviction: the unload round-trip (up to a 60 s
  // server timeout under memory pressure) used to block the whole mode
  // switch with zero feedback. Now the switch lands instantly and the
  // eviction reports back if it actually freed anything. Idempotent, so
  // rapid toggling is safe.
  function unloadInBackground(oldName, newName) {
    if (!oldName || !newName || oldName === newName) return
    unloadIfSwitching(oldName, newName).then((unloaded) => {
      if (unloaded) pushSystem(`// freed ${oldName} from memory`)
    })
  }

  // Leaving code mode = entering casual: restore the casual loadout
  // (model + ctx), disarm tools. Eviction runs in the background so the
  // switch itself is instant (see above).
  async function leaveCodeMode(echo) {
    const currentCtx = activeConversation?.context_length ?? chatDefaultsRef.current.context_length ?? 0
    const casualModel = loadout.casualModel || selectedModel
    const oldModel = activeConversation?.model || selectedModel
    unloadInBackground(oldModel, casualModel)
    const newCtx = loadout.casualCtx || currentCtx
    await applyModelCtx(casualModel, newCtx)
    if (loadout.casualCtx) {
      await api.saveSettings({ default_context_length: newCtx, loadout_casual_ctx: newCtx })
    }
    setCodeArmed(false)
    pushSystem(
      `${echo}\n\n// casual mode — model ${casualModel || '(unchanged)'} · ctx ${newCtx} · think ${loadout.casualThink === 'on' ? 'on' : 'off'} · tools off`,
    )
  }

  // Apply a model + context switch (loadout changes): updates the picker,
  // the active conversation (persisted per chat) and the new-chat defaults.
  async function applyModelCtx(name, ctx) {
    if (name) setSelectedModel(name)
    chatDefaultsRef.current = { ...chatDefaultsRef.current, context_length: ctx }
    if (activeConversation) {
      const patch = { context_length: ctx }
      if (name) patch.model = name
      const updated = await api.updateConversation(activeConversation.id, patch)
      if (updated) {
        setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
      }
    }
  }

  function sizeLabel(bytes) {
    if (!bytes) return ''
    return (bytes / 1e9).toFixed(1) + ' GB'
  }

  function resolveConversation(arg) {
    const byId = conversations.find((c) => c.id === Number(arg))
    if (byId) return byId
    return conversations[Number(arg) - 1]
  }

  async function handleCommand(raw) {
    const [cmd, ...args] = raw.trim().split(/\s+/)
    const arg = args.join(' ')
    const echo = `$ ${raw}`

    if (cmd === '/help') {
      const lines = COMMANDS.map((c) => `${c.cmd.padEnd(12)} ${c.desc}`)
      pushSystem(`${echo}\n\n${lines.join('\n')}`)
      return
    }

    if (cmd === '/models') {
      if (arg === 'get' || arg.startsWith('get ')) {
        const query = arg.slice(3).trim()
        const url = query ? `https://ollama.com/search?q=${encodeURIComponent(query)}` : 'https://ollama.com/search'
        pushSystem(`${echo}\n\n// browse the ollama model library:\n${url}`)
        return
      }
      if (arg === 'pull' || arg.startsWith('pull ')) {
        const name = arg.slice(4).trim()
        if (!name) {
          if (modelPullRef.current) {
            modelPullRef.current.abort()
            modelPullRef.current = null
            return
          }
          pushSystem(`${echo}\n\n// usage: /models pull <model> — e.g. /models pull deepseek-r1:1.5b`)
          return
        }
        const fmt = (b) => (b >= 1073741824 ? (b / 1073741824).toFixed(2) + ' GB' : Math.round(b / 1048576) + ' MB')
        const pullId = ++idRef.current
        const ctrl = new AbortController()
        modelPullRef.current = ctrl
        setMessages((prev) => [...prev, { id: pullId, role: 'system', content: `${echo}\n\n// pulling ${name}…` }])
        try {
          await api.pullModel(
            name,
            (evt) => {
              let line
              if (evt.error) line = `// pull failed: ${evt.error}`
              else if (evt.status === 'success') line = `// pulled ${name} — select with: /models ${name}`
              else if (evt.pct !== undefined)
                line = `// pulling ${name}… ${evt.pct}% (${fmt(evt.completed)} / ${fmt(evt.total)})`
              else line = `// ${evt.status} ${name}`
              setMessages((prev) => prev.map((m) => (m.id === pullId ? { ...m, content: `${echo}\n\n${line}` } : m)))
            },
            ctrl.signal,
          )
          const modelsRes = await api.getModels()
          setModels(modelsRes.models)
        } catch (err) {
          const msg = ctrl.signal.aborted ? '// pull cancelled' : `// pull failed: ${err.message}`
          setMessages((prev) => prev.map((m) => (m.id === pullId ? { ...m, content: `${echo}\n\n${msg}` } : m)))
        } finally {
          modelPullRef.current = null
        }
        return
      }
      if (!arg) {
        const lines = models.map((m, i) => `${String(i + 1).padStart(2)}. ${m.name.padEnd(24)} ${sizeLabel(m.size)}`)
        pushSystem(
          `${echo}\n\n${lines.join('\n')}\n\n// select with: /models <name or number>   // delete with: /models rm <name or number>`,
        )
        return
      }
      if (arg === 'rm' || arg.startsWith('rm ')) {
        const target = arg.slice(2).trim()
        if (!target) {
          pushSystem(`${echo}\n\n// usage: /models rm <name or number> — e.g. /models rm 2`)
          return
        }
        let name = target
        if (/^\d+$/.test(target)) {
          const picked = models[Number(target) - 1]
          if (!picked) {
            pushSystem(`${echo}\n\n// no model #${target} — try /models`)
            return
          }
          name = picked.name
        } else {
          const exact = models.find((m) => m.name === target)
          name = exact ? exact.name : target
        }
        try {
          await api.deleteModel(name)
          const modelsRes = await api.getModels()
          setModels(modelsRes.models)
          pushSystem(`${echo}\n\n// deleted ${name}`)
        } catch (err) {
          pushSystem(`${echo}\n\n// delete failed: ${err.message}`)
        }
        return
      }
      const byIndex = /^\d+$/.test(arg) ? models[Number(arg) - 1] : null
      const match = byIndex || models.find((m) => m.name === arg || m.name.includes(arg))
      if (!match) {
        pushSystem(`${echo}\n\n// no model matching "${arg}" — try /models`)
        return
      }
      await changeModel(match.name)
      pushSystem(`${echo}\n\n// model set to ${match.name}`)
      return
    }

    if (cmd === '/newchat') {
      const conversation = await newChat()
      pushSystem(`${echo}\n\n// started new chat #${conversation.id}`)
      return
    }

    if (cmd === '/chats') {
      if (!arg) {
        const lines = conversations.map(
          (c, i) => `${String(i + 1).padStart(2)}. [${c.id}] ${(c.title || 'new chat').slice(0, 50)}${c.id === activeId ? '  *' : ''}`,
        )
        pushSystem(
          `${echo}\n\n${lines.join('\n') || '// no conversations yet'}\n\n// open with: /chats <n or [id]>   // delete with: /delchat <n or [id]>`,
        )
        return
      }
      const conversation = resolveConversation(arg)
      if (!conversation) {
        pushSystem(`${echo}\n\n// no conversation #${arg} — try /chats`)
        return
      }
      await selectConversation(conversation.id)
      pushSystem(`${echo}\n\n// opened [${conversation.id}] ${conversation.title || 'new chat'}`)
      return
    }

    if (cmd === '/delchat') {
      if (arg.trim().toLowerCase() === 'all') {
        const res = await api.clearAllConversations()
        setConversations([])
        setActiveId(null)
        setMessages([])
        pushSystem(`${echo}\n\n// history cleared — ${res.deleted} conversation${res.deleted === 1 ? '' : 's'} deleted`)
        return
      }
      const conversation = resolveConversation(arg)
      if (!conversation) {
        pushSystem(`${echo}\n\n// no conversation #${arg} — try /chats`)
        return
      }
      await deleteConversation(conversation.id)
      pushSystem(`${echo}\n\n// deleted [${conversation.id}] ${conversation.title || 'new chat'}`)
      return
    }

    if (cmd === '/clear') {
      if (activeId) {
        const res = await api.clearConversation(activeId)
        setMessages([])
        if (activeConversation) {
          setConversations((prev) => prev.map((c) => (c.id === activeId ? { ...c, title: '' } : c)))
        }
        pushSystem(`${echo}\n\n// current chat cleared — ${res.cleared} message${res.cleared === 1 ? '' : 's'} gone, model and settings kept`)
      } else {
        setMessages([])
        pushSystem(`${echo}\n\n// nothing to clear — no chat open`)
      }
      return
    }

    if (cmd === '/settings') {
      // settings mount from DB truth — never open on stale pre-boot state,
      // or an early save could wipe persisted values with empties
      if (!bootedRef.current) {
        pushSystem(`${echo}\n\n// still starting — try /settings again in a moment`)
        return
      }
      pushSystem(`${echo}`)
      setSettingsOpen(true)
      return
    }

    if (cmd === '/eject') {
      const before = await api.getStatus()
      const res = await api.ejectServer()
      setStatus(await api.getStatus())
      const line = res.server_ok
        ? '// ollama is still running — it may be managed by a system service'
        : before.ok
          ? '// ollama server stopped — /connect to bring it back'
          : '// ollama server is already off — /connect to start it'
      pushSystem(`${echo}\n\n${line}`)
      return
    }

    if (cmd === '/connect') {
      const res = await api.connectServer()
      setStatus(await api.getStatus())
      const line = res.ok
        ? res.started
          ? `// ollama started — connected to ${res.url}\n// new here? pull a model in /settings, then /models <name> to chat`
          : '// ollama already running — connected'
        : `// ${res.error}`
      pushSystem(`${echo}\n\n${line}`)
      return
    }

    if (cmd === '/stats') {
      const next = !showStats
      setShowStats(next)
      await api.saveSettings({ show_stats: next })
      const line = next
        ? '// stats display: on — timings show under new replies and are saved with each message'
        : '// stats display: off'
      pushSystem(`${echo}\n\n${line}`)
      return
    }

    if (cmd === '/think') {
      const mode = arg.trim().toLowerCase()
      const current = activeConversation?.think ?? chatDefaultsRef.current.think ?? null
      let next = null
      if (!mode) {
        next = current === 'off' ? 'on' : current === 'on' ? 'off' : 'on'
      } else if (['on', 'true', '1'].includes(mode)) {
        next = 'on'
      } else if (['off', 'false', '0'].includes(mode)) {
        next = 'off'
      } else if (['auto', 'default', 'none'].includes(mode)) {
        next = 'auto'
      } else {
        pushSystem(`${echo}\n\n// usage: /think [on|off|auto] — e.g. /think off`)
        return
      }
      const value = next === 'auto' ? null : next
      if (activeConversation) {
        const updated = await api.updateConversation(activeConversation.id, { think: value === null ? 'auto' : value })
        if (updated) {
          setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
        }
      } else {
        chatDefaultsRef.current = { ...chatDefaultsRef.current, think: value }
        // no chat open: /think edits the casual loadout default (auto clears back to off)
        await api.saveSettings({ loadout_casual_think: value === null ? '' : value })
        setLoadout((l) => ({ ...l, casualThink: value === 'on' ? 'on' : 'off' }))
      }
      const label = value === null ? 'auto (model default)' : value
      pushSystem(`${echo}\n\n// thinking: ${label}${activeConversation ? '' : ' — applies to new chats'}`)
      return
    }

    if (cmd === '/ide') {
      const next = !ideOpen
      setIdeOpen(next)
      await api.saveSettings({ ide_open: next })
      const line = next ? '// ide pane: on' : '// ide pane: off'
      pushSystem(`${echo}\n\n${line}`)
      return
    }

    if (cmd === '/mkdir') {
      const name = arg.trim()
      if (!name) {
        pushSystem(`${echo}\n\n// usage: /mkdir <name> — e.g. /mkdir project_1 (created in the workspace root)`)
        return
      }
      try {
        const res = await api.mkdirWorkspace(name)
        pushSystem(`${echo}\n\n// folder ${res.exists ? 'already exists' : 'created'}: ${res.path}`)
      } catch (err) {
        pushSystem(`${echo}\n\n// ${err.message}`)
      }
      return
    }

    if (cmd === '/cd') {
      const name = arg.trim()
      if (!name) {
        const s = await api.getSettings()
        setWorkspace({ root: s.workspace_root || '', project: s.active_project || '' })
        pushSystem(`${echo}\n\n// root: ${s.workspace_root || '(unset)'}\n// project: ${s.active_project || '(none — /cd <name>)'}`)
        return
      }
      try {
        await api.saveSettings({ active_project: name })
        const s = await api.getSettings()
        setWorkspace({ root: s.workspace_root || '', project: s.active_project || '' })
        pushSystem(`${echo}\n\n// project: ${s.active_project} (root: ${s.workspace_root})`)
      } catch (err) {
        pushSystem(`${echo}\n\n// ${err.message}`)
      }
      return
    }

    if (cmd === '/code') {
      const rest = arg
      if (rest) {
        pushSystem(`${echo}\n\n// one-shot: tools armed for this message (model unchanged)`)
        await send(rest, { forceArmed: true })
      } else {
        const next = !codeArmed
        const currentCtx = activeConversation?.context_length ?? chatDefaultsRef.current.context_length ?? 0
        if (next) {
          // entering code mode: code loadout model + code ctx (at least 50000) + ide open.
          // State flips FIRST so the switch is instant; the slow model
          // eviction runs in the background (see unloadInBackground).
          const codeModel = loadout.codeModel || selectedModel
          const oldModel = activeConversation?.model || selectedModel
          const newCtx = Math.max(currentCtx, loadout.codeCtx || 50000)
          setCodeArmed(true)
          pushSystem(
            `${echo}\n\n// code mode: on — model ${codeModel || '(none selected)'} · ctx ${newCtx} · think on · ide open (persists until /code or /casual, off on restart)`,
          )
          unloadInBackground(oldModel, codeModel)
          await applyModelCtx(codeModel, newCtx)
          await api.saveSettings({ default_context_length: newCtx, loadout_code_ctx: newCtx })
          setLoadout((l) => ({ ...l, codeCtx: newCtx }))
          if (!ideOpen) {
            setIdeOpen(true)
            await api.saveSettings({ ide_open: true })
          }
        } else {
          await leaveCodeMode(echo)
        }
      }
      return
    }

    if (cmd === '/casual') {
      if (!codeArmed) {
        pushSystem(`${echo}\n\n// already casual — model ${selectedModel || '(none)'} · tools off`)
        return
      }
      await leaveCodeMode(echo)
      return
    }

    if (cmd === '/modes') {
      const mode = codeArmed ? 'code' : 'casual'
      const effModel = activeConversation?.model || selectedModel || '(none)'
      const effCtx = activeConversation?.context_length ?? chatDefaultsRef.current.context_length ?? 0
      const effThink =
        activeConversation?.think ?? (codeArmed ? 'on' : loadout.casualThink === 'on' ? 'on' : 'off')
      pushSystem(
        `${echo}\n\n// mode: ${mode}\n// model: ${effModel} (casual loadout: ${loadout.casualModel || '—'} · code loadout: ${loadout.codeModel || '—'})\n// ctx: ${effCtx} · think: ${effThink || 'auto'} · tools: ${codeArmed ? 'armed' : 'off'} · sysprompt: ${codeArmed ? 'on (code mode)' : 'off (casual)'} · engine: ${engine}${engine === 'gpu' && engineVulkan ? '+vulkan' : ''}\n// workspace: ${workspace.root || '(unset)'}${workspace.project ? ` · project: ${workspace.project}` : ''}`,
      )
      return
    }

    pushSystem(`${echo}\n\n// unknown command: ${cmd} — try /help`)
  }

  function attachIdeRun(text) {
    const finished =
      ideOutput.exitCode !== null && ideOutput.text && ideOutput.text.trim() && ideOutput !== ideRunSeenRef.current
    if (!finished) return text
    ideRunSeenRef.current = ideOutput
    const out = ideOutput.text
    const status = ideOutput.exitCode < 0 ? 'killed' : `exit ${ideOutput.exitCode}`
    const parts = [text, '', `// attached: ide run (${status})`, '', '```python', ideCode, '```']
    if (out.trim()) parts.push('', 'output:', '', '```', out, '```')
    return parts.join('\n')
  }

  async function send(content, opts = {}) {
    const trimmed = content.trim()
    if (!trimmed || streaming) return
    if (trimmed.startsWith('/') && !opts.forceArmed) {
      await handleCommand(trimmed)
      return
    }
    const outgoing = attachIdeRun(trimmed)
    // Tools are strictly code-mode. The old ```python auto-arm is gone:
    // casual promises "tools off" and means it.
    const arm = opts.forceArmed === true || codeArmed
    const codeMode = opts.forceArmed === true || codeArmed
    if (!selectedModel) return
    // think: explicit per-chat /think wins; otherwise code mode is fixed on,
    // casual follows the loadout toggle (off by default)
    const think = activeConversation?.think ?? (codeMode ? 'on' : (loadout.casualThink === 'on' ? 'on' : 'off'))
    let convId = activeId
    if (!activeConversation) {
      const conversation = await api.createConversation({ model: selectedModel, ...chatDefaultsRef.current })
      convId = conversation.id
      setConversations((prev) => [conversation, ...prev])
      setActiveId(convId)
    }
    const userMsg = { id: -++idRef.current, role: 'user', content: outgoing }
    const assistantMsg = { id: -++idRef.current, role: 'assistant', content: '' }
    setMessages((prev) => [...prev, userMsg, assistantMsg])
    streamTargetRef.current = assistantMsg.id
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let partial = ''
    let replyStats = null
    try {
      await api.streamChat(
        { conversation_id: convId, content: outgoing, model: selectedModel, tools: arm, think, code_mode: codeMode },
        {
          onUserId: (dbId) =>
            setMessages((prev) => prev.map((m) => (m.id === userMsg.id ? { ...m, id: dbId } : m))),
          onDone: (obj) => {
            if (obj?.assistant_id) {
              setMessages((prev) =>
                prev.map((m) => (m.id === assistantMsg.id ? { ...m, id: obj.assistant_id } : m)),
              )
              if (streamTargetRef.current === assistantMsg.id) streamTargetRef.current = obj.assistant_id
            }
          },
          onDelta: (delta) => {
            partial += delta
            const target = streamTargetRef.current
            setMessages((prev) =>
              prev.map((m) => (m.id === target ? { ...m, content: m.content + delta } : m)),
            )
          },
          onStats: (s) => {
            replyStats = s
            const target = streamTargetRef.current
            setMessages((prev) =>
              prev.map((m) => (m.id === target ? { ...m, stats: s } : m)),
            )
          },
          onToolStart: (t) => {
            const id = ++idRef.current
            pendingToolRef.current = id
            setMessages((prev) => [...prev, { id, role: 'system', content: `// running tool: ${t.name} …` }])
          },
          onTool: (t) => {
            const nextAssistantId = ++idRef.current
            setMessages((prev) => {
              const base = prev.filter((m) => m.id !== pendingToolRef.current)
              // Attach to the last ASSISTANT message by role, not position —
              // a mid-stream system line may sit after it.
              let targetIdx = -1
              for (let i = base.length - 1; i >= 0; i--) {
                if (base[i].role === 'assistant') { targetIdx = i; break }
              }
              const next = base.map((m, i) =>
                i === targetIdx
                  ? {
                      ...m,
                      content: t.replaces_text ? '' : m.content,
                      tool_calls: [
                        ...(m.tool_calls || []),
                        { function: { name: t.name, arguments: { code: t.code, path: t.path || '' } } },
                      ],
                    }
                  : m,
              )
              next.push({ id: t.id, role: 'tool', content: t.output })
              next.push({ id: nextAssistantId, role: 'assistant', content: '' })
              return next
            })
            streamTargetRef.current = nextAssistantId
            // Artifact bridge: an .html file the model wrote/edited opens
            // (or refreshes) in the preview pane instead of flooding chat.
            if ((t.name === 'ws_write' || t.name === 'ws_edit') && (t.exit === 0 || t.exit === null)) {
              const p = t.path || ''
              if (/\.html?$/i.test(p)) refreshFilePreview(p)
            }
          },
          onError: (error) => {
            if (!partial) {
              setMessages((prev) =>
                prev.map((m, i) =>
                  i === prev.length - 1 && m.role === 'assistant' && !m.content
                    ? { ...m, content: '⚠ ' + error }
                    : m,
                ),
              )
            }
          },
        },
        controller.signal,
      )
    } finally {
      setStreaming(false)
      abortRef.current = null
      streamTargetRef.current = null
    }
    const visible = splitThinking(partial)
      .filter((p) => !p.think)
      .map((p) => p.text)
      .join('\n')
    const block = extractLastPythonBlock(visible)
    const html = extractLastHtmlBlock(visible)
    if (html) openArtifact(html)
    else if (block) loadToIde(block)
    const convs = await api.getConversations()
    setConversations(convs.conversations)
  }

  function stop() {
    abortRef.current?.abort()
  }

  // Edit / regenerate: drop this user message and everything after it, then send again
  async function resendFrom(msg, newContent) {
    if (streaming) return
    try {
      await api.deleteMessageFrom(msg.id)
    } catch (err) {
      if (err.message !== 'Message not found') {
        pushSystem(`// could not truncate history: ${err.message}`)
        return
      }
      // not in the DB (e.g. a command echo) — just drop it locally and resend
    }
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === msg.id)
      return idx === -1 ? prev : prev.slice(0, idx)
    })
    await send(newContent ?? msg.content)
  }

  async function closeIde() {
    setIdeOpen(false)
    await api.saveSettings({ ide_open: false })
  }

  function extractLastPythonBlock(text) {
    const blocks = [...text.matchAll(/```python\n([\s\S]*?)```/g)]
    const last = blocks.length ? blocks[blocks.length - 1][1].replace(/\n$/, '') : null
    return last
  }

  function extractLastHtmlBlock(text) {
    const blocks = [...text.matchAll(/```html\n([\s\S]*?)```/g)]
    const last = blocks.length ? blocks[blocks.length - 1][1].replace(/\n$/, '') : null
    return last
  }

  function openArtifact(code, path = null) {
    setArtifact(code)
    setArtifactPath(path)
    setArtifactTab('preview')
    if (!ideOpen) {
      setIdeOpen(true)
      api.saveSettings({ ide_open: true })
    }
  }

  // File-backed preview: (re)load a workspace .html into the artifact pane.
  async function refreshFilePreview(path) {
    try {
      const res = await api.readWorkspaceFile(path)
      setArtifact(res.content)
      setArtifactPath(res.path)
      // note: tab untouched on refresh — your preview/code tab survives edits
      if (!ideOpen) {
        setIdeOpen(true)
        api.saveSettings({ ide_open: true })
      }
      pushSystem(`// preview: ${res.path}`)
    } catch (err) {
      pushSystem(`// preview failed for ${path}: ${err.message}`)
    }
  }

  async function downloadArtifact(code, css, js) {
    try {
      const res = await api.downloadArtifact(code, undefined, { css: css || undefined, js: js || undefined })
      pushSystem(`// artifact saved to ${res.path}`)
    } catch (err) {
      pushSystem(`// download failed: ${err.message}`)
    }
  }

  function loadToIde(code) {
    setArtifact(null)
    setArtifactPath(null)
    setIdeCode(code)
    if (!ideOpen) {
      setIdeOpen(true)
      api.saveSettings({ ide_open: true })
    }
    pushSystem(`// loaded ${code.split('\n').length} lines into the ide`)
  }

  function runInIde(code) {
    setArtifact(null)
    setArtifactPath(null)
    setIdeCode(code)
    if (!ideOpen) {
      setIdeOpen(true)
      api.saveSettings({ ide_open: true })
    }
    setRunSignal((s) => s + 1)
  }

  function sendIdeToChat() {
    ideRunSeenRef.current = ideOutput
    const { text, exitCode } = ideOutput
    const out = text
    const status = exitCode === null ? 'not run' : exitCode < 0 ? 'killed' : `exit ${exitCode}`
    const parts = [
      'Here is the code currently in my IDE editor:',
      '',
      '```python',
      ideCode,
      '```',
    ]
    if (out.trim()) {
      parts.push('', `Output from the last run (${status}):`, '', '```', out, '```')
    } else {
      parts.push('', `I have not run it yet (${status}).`)
    }
    send(parts.join('\n'))
  }

  function startResize(e) {
    if (e.button !== 0) return
    e.preventDefault()
    // Pointer capture keeps move/up events flowing to the handle even when
    // the cursor crosses the artifact iframe (whose document would otherwise
    // swallow them, leaving a stuck drag that follows the mouse forever).
    const handle = e.currentTarget
    try {
      handle.setPointerCapture(e.pointerId)
    } catch { /* older engines: fall back to window listeners */ }
    let ended = false
    const onMove = (ev) => {
      if (ended) return
      // Belt-and-suspenders: if no button is held, this is a stale drag —
      // end it instead of chasing the mouse.
      if (ev.buttons !== undefined && ev.buttons !== 0 && (ev.buttons & 1) === 0) {
        onUp()
        return
      }
      const next = Math.min(1200, Math.max(280, window.innerWidth - ev.clientX))
      widthRef.current = next
      setIdeWidth(next)
    }
    const onUp = () => {
      if (ended) return
      ended = true
      handle.removeEventListener('pointermove', onMove)
      handle.removeEventListener('pointerup', onUp)
      handle.removeEventListener('pointercancel', onUp)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      moveRef.current = null
      upRef.current = null
      api.saveSettings({ ide_width: widthRef.current })
    }
    moveRef.current = onMove
    upRef.current = onUp
    handle.addEventListener('pointermove', onMove)
    handle.addEventListener('pointerup', onUp)
    handle.addEventListener('pointercancel', onUp)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  async function saveSettings({ ollamaUrl, systemPrompt, temperature, contextLength, accent: newAccent, sandboxTools: sandboxPref, loadoutCasualModel, loadoutCodeModel, loadoutCasualCtx, loadoutCodeCtx, loadoutCasualThink, bgBrightness: newBrightness, bgContrast: newContrast, engine: newEngine, engineVulkan: vulkanPref, workspaceRoot, activeProject }) {
    // Autosaved on every change (no Save button) — stay open, skip invalid
    // mid-typing values instead of failing the whole patch.
    const url = (ollamaUrl || '').trim()
    const urlOk = url.startsWith('http://') || url.startsWith('https://')
    const tempOk = temperature === undefined || Number.isFinite(temperature)
    // New chats follow the casual loadout ctx (falls back to the per-chat value).
    const newDefaultCtx = loadoutCasualCtx || contextLength
    await api.saveSettings({
      ...(urlOk ? { ollama_url: url } : {}),
      accent: newAccent,
      ...(sandboxPref === undefined ? {} : { sandbox_tools: sandboxPref }),
      default_system_prompt: systemPrompt,
      ...(tempOk ? { default_temperature: temperature } : {}),
      default_context_length: newDefaultCtx,
      ...(loadoutCasualThink === undefined ? {} : { loadout_casual_think: loadoutCasualThink }),
      ...(loadoutCasualModel === undefined ? {} : { loadout_casual_model: loadoutCasualModel }),
      ...(loadoutCodeModel === undefined ? {} : { loadout_code_model: loadoutCodeModel }),
      ...(loadoutCasualCtx === undefined ? {} : { loadout_casual_ctx: loadoutCasualCtx }),
      ...(loadoutCodeCtx === undefined ? {} : { loadout_code_ctx: loadoutCodeCtx }),
      ...(newBrightness === undefined ? {} : { bg_brightness: newBrightness }),
      ...(newContrast === undefined ? {} : { bg_contrast: newContrast }),
      ...(newEngine === undefined ? {} : { engine: newEngine }),
      ...(vulkanPref === undefined ? {} : { engine_vulkan: vulkanPref }),
      ...(workspaceRoot === undefined ? {} : { workspace_root: workspaceRoot }),
      ...(activeProject === undefined ? {} : { active_project: activeProject }),
    })
    if (workspaceRoot !== undefined || activeProject !== undefined) {
      const s = await api.getSettings()
      setWorkspace({ root: s.workspace_root || '', project: s.active_project || '' })
    }
    if (newEngine !== undefined) setEngine(newEngine)
    if (vulkanPref !== undefined) setEngineVulkan(vulkanPref)
    if (loadoutCasualModel !== undefined || loadoutCodeModel !== undefined || loadoutCasualCtx !== undefined || loadoutCodeCtx !== undefined || loadoutCasualThink !== undefined) {
      setLoadout((l) => ({
        casualModel: loadoutCasualModel !== undefined ? loadoutCasualModel : l.casualModel,
        codeModel: loadoutCodeModel !== undefined ? loadoutCodeModel : l.codeModel,
        casualCtx: loadoutCasualCtx !== undefined ? loadoutCasualCtx : l.casualCtx,
        codeCtx: loadoutCodeCtx !== undefined ? loadoutCodeCtx : l.codeCtx,
        casualThink: loadoutCasualThink !== undefined ? (loadoutCasualThink === 'on' ? 'on' : 'off') : l.casualThink,
      }))
    }
    chatDefaultsRef.current = {
      system_prompt: systemPrompt,
      temperature,
      context_length: newDefaultCtx,
      think: loadoutCasualThink !== undefined ? (loadoutCasualThink === 'on' ? 'on' : 'off') : chatDefaultsRef.current.think,
    }
    setStatus(await api.getStatus())
    setAccent(newAccent)
    if (newBrightness !== undefined) setBgBrightness(newBrightness)
    if (newContrast !== undefined) setBgContrast(newContrast)
    if (activeConversation) {
      const updated = await api.updateConversation(activeConversation.id, {
        system_prompt: systemPrompt,
        ...(tempOk ? { temperature } : {}),
        context_length: contextLength,
      })
      if (updated) {
        setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
      }
    }
  }

  const currentModel = activeConversation?.model || selectedModel
  // header shows the effective think: per-chat /think wins, else code is on, else casual toggle
  const currentThink = activeConversation?.think ?? (codeArmed ? 'on' : (loadout.casualThink === 'on' ? 'on' : 'off'))

  async function changeSettingsView(view) {
    setSettingsView(view)
    await api.saveSettings({ settings_view: view })
  }

  // Double-click on the header (not on buttons/inputs) toggles maximize.
  const onHeaderDouble = (e) => {
    if (e.target.closest && (e.target.closest('.tb-controls') || e.target.closest('button') || e.target.closest('input'))) return
    try { window?.pywebview?.api?.toggle_maximize?.() } catch { /* browser dev */ }
  }

  return (
    <div className="window">
      <div className="app">
      <main className="main">
        <header className="app-header pywebview-drag-region" onDoubleClick={onHeaderDouble}>
          <div className="brand-line">
            <Logo size={20} />
            <span className="brand">Su1ra</span>
            <span className="brand-ver">v0.3.0</span>
            <span className={`status-tag${status?.ok ? ' ok' : ''}`}>
              [{status?.ok ? 'ok' : 'offline'}]
            </span>
            <span style={{ flex: 1 }} />
            <WindowControls />
          </div>
          <div className="chat-meta">
            <span className="hash">#</span>
            {activeConversation?.title || 'no chat'}
            <span className="meta-model"> · {codeArmed ? 'code' : 'casual'} · model: {currentModel || 'none'} · think: {currentThink || 'auto'}</span>
          </div>
        </header>
        <ChatView messages={messages} status={status} streaming={streaming} showStats={showStats} onLoadToIde={loadToIde} onRunCode={runInIde} onDownloadArtifact={downloadArtifact} onOpenArtifact={openArtifact} onOllamaReady={refreshStatus} onResendFrom={resendFrom} />
        <Composer commands={COMMANDS} disabled={!currentModel} streaming={streaming} onSend={send} onStop={stop} codeArmed={codeArmed} />
      </main>
      {ideOpen && (
        <>
          <div className="ide-resize" onMouseDown={startResize} />
          {artifact !== null ? (
            <ArtifactPane
              width={ideWidth}
              code={artifact}
              path={artifactPath}
              tab={artifactTab}
              onTab={setArtifactTab}
              onClose={closeIde}
              onDownload={() => downloadArtifact(artifact)}
            />
          ) : (
            <IdePane
              width={ideWidth}
              code={ideCode}
              onCodeChange={setIdeCode}
              onClose={closeIde}
              onResizeStart={startResize}
              onOutputChange={setIdeOutput}
              onSendToChat={sendIdeToChat}
              runSignal={runSignal}
            />
          )}
        </>
      )}
      {settingsOpen && (
          <SettingsModal
            status={status}
            conversation={activeConversation}
            model={activeConversation?.model || ''}
            models={models}
            loadout={loadout}
            view={settingsView}
            onViewChange={changeSettingsView}
            bgBrightness={bgBrightness}
            bgContrast={bgContrast}
            engine={engine}
            engineVulkan={engineVulkan}
            onServerChanged={refreshStatus}
            accent={accent}
            sandboxTools={sandboxTools}
            workspace={workspace}
            defaultSystemPrompt={chatDefaultsRef.current.system_prompt || ''}
            onSave={saveSettings}
            onClose={() => setSettingsOpen(false)}
            onOpenModels={() => { setSettingsOpen(false); setModelHubOpen(true) }}
          />
      )}
      {modelHubOpen && (
        <ModelHub
          models={models}
          onModelsChanged={() => api.getModels().then((r) => setModels(r.models))}
          onClose={() => setModelHubOpen(false)}
        />
      )}
      {ctxMenu && (
        <div className="ctx-menu" style={{ left: ctxMenu.x, top: ctxMenu.y }}>
          <button className="ctx-copy" onClick={copySelection}>
            {ctxMenu.done === true ? '[ copied ]' : ctxMenu.done === false ? '[ copy failed ]' : '[ copy ]'}
          </button>
        </div>
      )}
      </div>
    </div>
  )
}
