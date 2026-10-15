import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api'
import { applyAccent, applyBackground, DEFAULT_ACCENT, DEFAULT_BRIGHTNESS, DEFAULT_CONTRAST, readInjectedTheme } from './theme'
import ChatView, { splitThinking } from './components/ChatView.jsx'
import Composer from './components/Composer.jsx'
import Logo from './components/Logo.jsx'
import SettingsModal from './components/SettingsModal.jsx'
import ModelHub from './components/ModelHub.jsx'
import EditorPane from './components/EditorPane.jsx'
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
  { cmd: '/build', desc: 'toggle build mode — switches to the build loadout model/ctx, unloads the casual model; /build <msg> arms one message' },
  { cmd: '/casual', desc: 'switch to casual mode — everyday chat model, unloads the build model, tools off' },
  { cmd: '/modes', desc: 'show current mode — casual/build plus model, ctx, think, tools' },
  { cmd: '/editor', desc: 'toggle the editor pane — save/run scratch files (py, js, sh, ps1, bat, rb, pl, lua)' },
  { cmd: '/mkdir', desc: 'new project folder in the workspace — /mkdir <name>' },
  { cmd: '/cd', desc: 'switch active project — /cd <name>, or bare /cd to show root + project' },
  { cmd: '/preview', desc: 'generate + open a preview for a project file — /preview <name.pptx|xlsx|docx|pdf|svg>' },
  { cmd: '/web', desc: 'open the browser pane — /web <url or search query> (search uses the selected engine)' },
]

const STARTER_CODE = `# scratch.py — lives in ~/Documents/.scratch
# rename it (e.g. notes.md, run.js) — the extension picks the interpreter
print("hello from su1ra")

for i in range(3):
    print(f"tick {i}")`

const ENGINES = {
  google: { name: 'Google', home: 'https://www.google.com/', search: 'https://www.google.com/search?q=' },
  brave: { name: 'Brave', home: 'https://search.brave.com/', search: 'https://search.brave.com/search?q=' },
  ddg: { name: 'DuckDuckGo', home: 'https://duckduckgo.com/', search: 'https://duckduckgo.com/?q=' },
  yandex: { name: 'Yandex', home: 'https://yandex.com/', search: 'https://yandex.com/search/?text=' },
  bing: { name: 'Bing', home: 'https://www.bing.com/', search: 'https://www.bing.com/search?q=' },
}

function toUrl(input, engine) {
  const s = String(input || '').trim()
  if (s.startsWith('http://') || s.startsWith('https://')) return s
  if (!/\s/.test(s) && s.includes('.')) return 'https://' + s
  return ENGINES[engine].search + encodeURIComponent(s)
}

function unwrapRedirect(url) {
  try {
    const u = new URL(url)
    if (/(^|\.)bing\.com$/.test(u.hostname) && u.pathname === '/ck/a') {
      const enc = u.searchParams.get('u') || ''
      if (enc.startsWith('a1')) {
        const b64 = enc.slice(2).replace(/-/g, '+').replace(/_/g, '/')
        const target = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4))
        return new URL(target, 'https://www.bing.com/').href
      }
    }
  } catch { /* not a decodable redirect: keep as-is */ }
  return url
}

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
  const [editorOpen, setEditorOpen] = useState(false)
  const [editorWidth, setEditorWidth] = useState(460)
  const [editorCode, setEditorCode] = useState(STARTER_CODE)
  const [editorName, setEditorName] = useState('scratch.py')
  const [editorOutput, setEditorOutput] = useState({ text: '', exitCode: null })
  const [artifact, setArtifact] = useState(null)
  const [artifactTab, setArtifactTab] = useState('preview')
  const [artifactPath, setArtifactPath] = useState(null)
  const [browserUrl, setBrowserUrl] = useState(null)
  const [browserHistory, setBrowserHistory] = useState([])
  const [browserIndex, setBrowserIndex] = useState(-1)
  const [browserEngine, setBrowserEngine] = useState('bing')
  const [workspace, setWorkspace] = useState({ root: '', project: '' })
  const [codeArmed, setCodeArmed] = useState(false)
  const [casualSysp, setCasualSysp] = useState('')
  const [sandboxTools, setSandboxTools] = useState(true)
  const [sandboxBackend, setSandboxBackend] = useState('auto')
  const [loadout, setLoadout] = useState({ casualModel: '', codeModel: '', casualCtx: 0, codeCtx: 0, casualThink: 'off' })
  const [engine, setEngine] = useState('auto')
  const [engineVulkan, setEngineVulkan] = useState(false)
  const [settingsView, setSettingsView] = useState('split')
  const [pendingAttachments, setPendingAttachments] = useState([])
  const [visionModel, setVisionModel] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const addFilesRef = useRef(() => {})
  const abortRef = useRef(null)
  const modelPullRef = useRef(null)
  const pendingToolRef = useRef(null)
  // Deltas/stats must target the streaming assistant message BY ID, never by
  // position: mid-stream system lines (background unload notes, tool status)
  // would otherwise hijack following tokens into the wrong bubble and even
  // break think-tag parsing with glued text.
  const streamTargetRef = useRef(null)
  const editorRunSeenRef = useRef(null)
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

  // Vision capability gates the composer's [+] button. Best-effort: a failed
  // probe just hides the button rather than breaking the composer.
  useEffect(() => {
    let alive = true
    if (!selectedModel) {
      setVisionModel(false)
      return
    }
    api
      .getModelCaps(selectedModel)
      .then((caps) => {
        if (alive) setVisionModel(!!caps.vision)
      })
      .catch(() => {
        if (alive) setVisionModel(false)
      })
    return () => {
      alive = false
    }
  }, [selectedModel])

  // App-wide drag & drop. Two jobs:
  //  1. Guard: always preventDefault on dragover/drop so the webview never
  //     navigates to a dropped file:// (which would replace the whole UI).
  //  2. Accept: dropping files anywhere in the window adds them, and a
  //     full-window overlay shows while a drag is in progress.
  //
  // Listeners are attached in the CAPTURE phase on `document`: that runs
  // top-down before any target (e.g. the textarea, which would otherwise
  // insert the file path) can act on the event, so preventDefault reliably
  // cancels the native default.
  useEffect(() => {
    let depth = 0
    const dbg = (...a) => {
      if (!window.__SU1RA_DEBUG__) return
      const msg = a.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join(' ')
      console.log('[su1ra:dnd]', ...a)
      try {
        fetch('/api/client-log', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg }),
        })
      } catch {}
    }
    // Wayland/Hyprland delivers drags as `text/uri-list` (+ `text/html`), not
    // the browser-standard `Files`. So accept either, and always preventDefault
    // on anything that looks like a drag so the webview never navigates.
    function dragTypes(e) {
      return Array.from(e.dataTransfer?.types || [])
    }
    function isFileDrag(e) {
      const types = dragTypes(e)
      return types.includes('Files') || types.includes('text/uri-list')
    }
    function urisToFiles(e) {
      const raw = e.dataTransfer?.getData('text/uri-list') || ''
      const uris = raw
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter((s) => s && !s.startsWith('#'))
      const names = uris.map((u) => {
        try {
          return decodeURIComponent(u.replace(/^file:\/\//, '').split('/').pop() || '')
        } catch {
          return ''
        }
      })
      return { uris, names }
    }
    function onDragEnter(e) {
      dbg('dragenter', dragTypes(e), 'target=', e.target?.tagName)
      if (!isFileDrag(e)) return
      e.preventDefault()
      depth += 1
      setDragActive(true)
    }
    function onDragOver(e) {
      if (!isFileDrag(e)) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    }
    function onDragLeave(e) {
      if (!isFileDrag(e)) return
      depth = Math.max(0, depth - 1)
      if (depth === 0) setDragActive(false)
    }
    async function onDrop(e) {
      const types = dragTypes(e)
      const files = Array.from(e.dataTransfer?.files || [])
      const { uris, names } = urisToFiles(e)
      dbg('drop', 'types=', types, 'files=', files.length, 'names=', files.map((f) => f.name), 'uris=', uris)
      if (!isFileDrag(e)) {
        dbg('drop ignored: not a file drag')
        return
      }
      e.preventDefault()
      e.stopPropagation()
      depth = 0
      setDragActive(false)
      // pywebview (Linux/GTK) attaches the real absolute path to each dropped
      // file as `pywebviewFullPath` — the only reliable source on Wayland.
      const withPaths = files.filter((f) => f.pywebviewFullPath)
      if (withPaths.length) {
        dbg('using pywebviewFullPath', withPaths.map((f) => f.pywebviewFullPath))
        addFilesRef.current(withPaths.map((f) => ({ __path: f.pywebviewFullPath, name: f.name })))
        return
      }
      if (files.length) {
        addFilesRef.current(files)
        return
      }
      // Wayland: dataTransfer is empty. Ask pywebview's native bridge for the
      // paths its GTK backend captured from the drag.
      try {
        const native = await window.pywebview?.api?.takePaths?.()
        if (native && native.length) {
          dbg('using native takePaths', native)
          addFilesRef.current(native.map((p) => ({ __path: p, name: p.split('/').pop() })))
          return
        }
      } catch (err) {
        dbg('takePaths failed', String(err))
      }
      if (uris.length) {
        // URI-only drop: the webview cannot read these paths itself, so ask
        // the backend to load them from disk by path.
        addFilesRef.current(names.map((name, i) => ({ __path: uris[i], name })))
      } else {
        dbg('drop had no usable file source')
      }
    }
    const opts = { capture: true }
    document.addEventListener('dragenter', onDragEnter, opts)
    document.addEventListener('dragover', onDragOver, opts)
    document.addEventListener('dragleave', onDragLeave, opts)
    document.addEventListener('drop', onDrop, opts)
    return () => {
      document.removeEventListener('dragenter', onDragEnter, opts)
      document.removeEventListener('dragover', onDragOver, opts)
      document.removeEventListener('dragleave', onDragLeave, opts)
      document.removeEventListener('drop', onDrop, opts)
    }
  }, [])

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
      setCasualSysp(settingsRes.default_system_prompt_casual || '')
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
      setEditorOpen(settingsRes.ide_open === true)
      setEditorWidth(typeof settingsRes.ide_width === 'number' ? settingsRes.ide_width : 460)
      setSandboxTools(settingsRes.sandbox_tools !== false)
      setSandboxBackend(['auto', 'wsl', 'off'].includes(settingsRes.sandbox_backend) ? settingsRes.sandbox_backend : 'auto')
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
    widthRef.current = editorWidth
  }, [editorWidth])

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
    // Mode follows the chat: opening an old build chat while armed for
    // casual (or vice versa) flips the desk first, so tools/think/prompt
    // resolution match what the chat was built with. Deliberately lighter
    // than /build — this restores state, it doesn't rewrite the loadout
    // settings or force the IDE open.
    const wantBuild = !!detail.conversation.code_mode
    if (wantBuild !== codeArmed) {
      const targetModel = wantBuild ? (loadout.codeModel || selectedModel) : (loadout.casualModel || selectedModel)
      unloadInBackground(selectedModel, targetModel)
      setCodeArmed(wantBuild)
      if (targetModel) setSelectedModel(targetModel)
      chatDefaultsRef.current = {
        ...chatDefaultsRef.current,
        context_length: wantBuild ? Math.max(chatDefaultsRef.current.context_length || 0, loadout.codeCtx || 0) : (loadout.casualCtx || 0),
      }
      pushSystem(`// ${wantBuild ? 'build' : 'casual'} mode — switched to match chat [${id}]`)
    }
    setActiveId(detail.conversation.id)
    setMessages(detail.messages)
    setSelectedModel(detail.conversation.model || selectedModel)
  }

  async function newChat() {
    if (blocked) return
    // No system_prompt stamp — the backend resolves per-mode defaults at send
    // time. The chat is tagged with the mode it was born in.
    const { system_prompt: _omit, ...defaults } = chatDefaultsRef.current
    const conversation = await api.createConversation({ model: selectedModel, ...defaults, code_mode: codeArmed })
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

  // Mode switch = a fresh chat on the new desk. The chat being left keeps
  // its own mode and stays listed under its /chats column. An EMPTY chat
  // (no messages yet — nothing has committed it to a mode) is retagged and
  // reused instead, so toggling back and forth can't stack empty shells.
  async function startModeChat(isBuild, model, ctx) {
    if (activeConversation && messages.length === 0) {
      const updated = await api.updateConversation(activeConversation.id, {
        code_mode: isBuild,
        ...(model ? { model } : {}),
        context_length: ctx,
      })
      if (updated) setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
      return activeConversation
    }
    // No system_prompt stamp — the backend resolves per-mode defaults at send
    // time. The chat is tagged with the mode it was born in.
    const { system_prompt: _omit, ...defaults } = chatDefaultsRef.current
    const conversation = await api.createConversation({
      model: model || selectedModel,
      ...defaults,
      context_length: ctx,
      code_mode: isBuild,
    })
    setConversations((prev) => [conversation, ...prev])
    setActiveId(conversation.id)
    setMessages([])
    return conversation
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

  // Leaving code mode = entering casual: restore the casual loadout (picker +
  // new-chat defaults — the chat being left is NOT touched; it keeps its mode
  // and history) and open a fresh casual chat. Eviction runs in the background
  // so the switch itself is instant (see unloadInBackground).
  async function leaveCodeMode(echo) {
    const casualModel = loadout.casualModel || selectedModel
    const oldModel = activeConversation?.model || selectedModel
    unloadInBackground(oldModel, casualModel)
    const newCtx = loadout.casualCtx || chatDefaultsRef.current.context_length || 0
    if (casualModel) setSelectedModel(casualModel)
    chatDefaultsRef.current = { ...chatDefaultsRef.current, context_length: newCtx }
    if (loadout.casualCtx) {
      await api.saveSettings({ default_context_length: newCtx, loadout_casual_ctx: newCtx })
    }
    setCodeArmed(false)
    const conversation = await startModeChat(false, casualModel, newCtx)
    pushSystem(
      `${echo}\n\n// casual mode — new chat #${conversation.id} · model ${casualModel || '(unchanged)'} · ctx ${newCtx} · think ${loadout.casualThink === 'on' ? 'on' : 'off'} · tools off`,
    )
  }

  // Apply a model + context switch to the DESK (picker + new-chat defaults)
  // without touching any conversation. Mode switches use startModeChat; the
  // loadout pickers in settings go through saveSettings.
  function applyModelCtx(name, ctx) {
    if (name) setSelectedModel(name)
    chatDefaultsRef.current = { ...chatDefaultsRef.current, context_length: ctx }
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

    if (cmd === '/web') {
      if (!arg) {
        openBrowser(ENGINES[browserEngine].home)
        pushSystem(`${echo}\n\n// opened the browser pane`)
      } else {
        openBrowser(toUrl(arg, browserEngine))
        pushSystem(`${echo}\n\n// opened in the browser pane`)
      }
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
        if (!conversations.length) {
          pushSystem(`${echo}\n\n// no chats yet — /newchat or just start typing`)
          return
        }
        // Two columns: BUILD on the left, CASUAL on the right. Ordinals are
        // global (same list /chats <n|id> and /delchat resolve against).
        const W = 34
        const cell = (s) => {
          const t = s.length > W ? s.slice(0, W - 1) + '…' : s
          return t.padEnd(W)
        }
        const label = (c) => {
          const n = conversations.indexOf(c) + 1
          return `${String(n).padStart(2)}. [${c.id}] ${(c.title || 'new chat').slice(0, 22)}${c.id === activeId ? ' *' : ''}`
        }
        const build = conversations.filter((c) => c.code_mode)
        const casual = conversations.filter((c) => !c.code_mode)
        const lines = [cell('// BUILD') + '// CASUAL']
        const rows = Math.min(Math.max(build.length, casual.length), 20)
        for (let i = 0; i < rows; i++) {
          lines.push(cell(build[i] ? label(build[i]) : '') + (casual[i] ? label(casual[i]) : ''))
        }
        const overflow = Math.max(build.length, casual.length) - 20
        if (overflow > 0) lines.push(`// …and ${overflow} more`)
        pushSystem(
          `${echo}\n\n${lines.join('\n')}\n\n// open: /chats <n or [id]>   // delete: /delchat <n or [id]>\n// opening a build chat switches to build mode (and back)`,
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

    if (cmd === '/editor' || cmd === '/ide') { // /ide kept as a hidden alias
      const next = !editorOpen
      setEditorOpen(next)
      await api.saveSettings({ ide_open: next })
      const line = next
        ? '// editor: on — save/run scratch files; the extension picks the interpreter (py, js, sh, ps1, bat, rb, pl, lua)'
        : '// editor: off'
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

    if (cmd === '/preview') {
      const file = arg.trim()
      if (!file) {
        pushSystem(`${echo}\n\n// usage: /preview <file> — pptx/xlsx/docx/pdf/svg in the current project`)
        return
      }
      try {
        const res = await api.previewFile(file)
        pushSystem(`${echo}\n\n// preview: ${res.path} (from ${res.source})`)
        await refreshFilePreview(res.path)
      } catch (err) {
        pushSystem(`${echo}\n\n// preview failed: ${err.message}`)
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

    if (cmd === '/build' || cmd === '/code') { // /code kept as a hidden alias
      const rest = arg
      if (rest) {
        pushSystem(`${echo}\n\n// one-shot: tools armed for this message (model unchanged)`)
        await send(rest, { forceArmed: true })
      } else {
        const next = !codeArmed
        if (next) {
          // Entering build mode: code loadout model + code ctx (at least
          // 50000) + ide open + a FRESH BUILD CHAT. The chat being left is
          // untouched (keeps its mode + history; an empty chat is reused).
          // State flips FIRST so the switch is instant; the slow model
          // eviction runs in the background (see unloadInBackground).
          const codeModel = loadout.codeModel || selectedModel
          const oldModel = activeConversation?.model || selectedModel
          const newCtx = Math.max(chatDefaultsRef.current.context_length || 0, loadout.codeCtx || 50000)
          setCodeArmed(true)
          unloadInBackground(oldModel, codeModel)
          applyModelCtx(codeModel, newCtx)
          await api.saveSettings({ default_context_length: newCtx, loadout_code_ctx: newCtx })
          setLoadout((l) => ({ ...l, codeCtx: newCtx }))
          if (!editorOpen) {
            setEditorOpen(true)
            await api.saveSettings({ ide_open: true })
          }
          const conversation = await startModeChat(true, codeModel, newCtx)
          pushSystem(
            `${echo}\n\n// build mode: on — new chat #${conversation.id} · model ${codeModel || '(none selected)'} · ctx ${newCtx} · think on · ide open (persists until /build or /casual, off on restart)`,
          )
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
      const mode = codeArmed ? 'build' : 'casual'
      const effModel = activeConversation?.model || selectedModel || '(none)'
      const effCtx = activeConversation?.context_length ?? chatDefaultsRef.current.context_length ?? 0
      const effThink =
        activeConversation?.think ?? (codeArmed ? 'on' : loadout.casualThink === 'on' ? 'on' : 'off')
      // sysprompt state reflects the real resolution: per-chat override, else
      // the mode's default (build = sysp.txt, casual = its own default).
      const effSysp =
        (activeConversation?.system_prompt || '').trim() ||
        (codeArmed ? chatDefaultsRef.current.system_prompt || '' : casualSysp)
      const syspLabel = effSysp
        ? `on (${(activeConversation?.system_prompt || '').trim() ? 'per-chat' : mode === 'build' ? 'sysp.txt' : 'casual default'})`
        : 'off'
      pushSystem(
        `${echo}\n\n// mode: ${mode}\n// model: ${effModel} (casual loadout: ${loadout.casualModel || '—'} · build loadout: ${loadout.codeModel || '—'})\n// ctx: ${effCtx} · think: ${effThink || 'auto'} · tools: ${codeArmed ? 'armed' : 'off'} · sysprompt: ${syspLabel} · engine: ${engine}${engine === 'gpu' && engineVulkan ? '+vulkan' : ''}\n// workspace: ${workspace.root || '(unset)'}${workspace.project ? ` · project: ${workspace.project}` : ''}`,
      )
      return
    }

    pushSystem(`${echo}\n\n// unknown command: ${cmd} — try /help`)
  }

  function attachEditorRun(text) {
    const finished =
      editorOutput.exitCode !== null && editorOutput.text && editorOutput.text.trim() && editorOutput !== editorRunSeenRef.current
    if (!finished) return text
    editorRunSeenRef.current = editorOutput
    const out = editorOutput.text
    const status = editorOutput.exitCode < 0 ? 'killed' : `exit ${editorOutput.exitCode}`
    const lang = (editorName.split('.').pop() || 'txt').toLowerCase()
    const parts = [text, '', `// attached: editor run — ${editorName} (${status})`, '', '```' + lang, editorCode, '```']
    if (out.trim()) parts.push('', 'output:', '', '```', out, '```')
    return parts.join('\n')
  }

  async function addFiles(files) {
    if (!files || files.length === 0) return
    if (window.__SU1RA_DEBUG__) {
      const msg = `addFiles ${files.map((f) => (f.__path ? `${f.name} (path: ${f.__path})` : `${f.name} (${f.type || 'no type'}, ${f.size}b)`)).join(', ')}`
      console.log('[su1ra:dnd]', msg)
      try {
        fetch('/api/client-log', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg }),
        })
      } catch {}
    }
    // Attachments need a conversation to belong to. If none is active yet,
    // create one lazily (same defaults the send path uses).
    let convId = activeId
    if (!activeConversation) {
      const { system_prompt: _omit, ...defaults } = chatDefaultsRef.current
      const conversation = await api.createConversation({ model: selectedModel, ...defaults, code_mode: codeArmed })
      convId = conversation.id
      setConversations((prev) => [conversation, ...prev])
      setActiveId(convId)
    }
    for (const file of files) {
      try {
        const ref = file.__path
          ? await api.uploadAttachmentFromPath(convId, file.__path, file.name)
          : await api.uploadAttachment(convId, file)
        setPendingAttachments((prev) => {
          const kind = ref.kind === 'document' ? 'document' : 'image'
          const sameKind = prev.filter((a) => (a.kind === 'document' ? 'document' : 'image') === kind)
          const next = {
            ...ref,
            kind,
            url: kind === 'image' ? api.attachmentUrl(ref.id) : null,
            localId: ref.id,
          }
          if (kind === 'document') next.docIndex = sameKind.length + 1
          else next.imgIndex = sameKind.length + 1
          return [...prev, next]
        })
      } catch (err) {
        pushSystem(`// file rejected: ${err.message}`)
      }
    }
  }
  addFilesRef.current = addFiles

  function removeAttachment(att) {
    setPendingAttachments((prev) => prev.filter((a) => a.localId !== att.localId))
  }

  async function send(content, opts = {}) {
    const trimmed = content.trim()
    const atts = opts.forceArmed ? [] : pendingAttachments
    if ((!trimmed && atts.length === 0) || streaming) return
    if (trimmed.startsWith('/') && !opts.forceArmed) {
      await handleCommand(trimmed)
      return
    }
    const outgoing = attachEditorRun(trimmed)
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
      // Never stamp a system prompt into the new chat — the backend resolves
      // per-mode defaults at send time (build = sysp.txt, casual = its own
      // default). Tag the chat with the mode it was born in.
      const { system_prompt: _omit, ...defaults } = chatDefaultsRef.current
      const conversation = await api.createConversation({ model: selectedModel, ...defaults, code_mode: codeMode })
      convId = conversation.id
      setConversations((prev) => [conversation, ...prev])
      setActiveId(convId)
    }
    const attachmentIds = atts.map((a) => a.id)
    const userMsg = { id: -++idRef.current, role: 'user', content: outgoing, attachments: atts }
    const assistantMsg = { id: -++idRef.current, role: 'assistant', content: '' }
    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setPendingAttachments([])
    streamTargetRef.current = assistantMsg.id
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let partial = ''
    let replyStats = null
    try {
      await api.streamChat(
        {
          conversation_id: convId,
          content: outgoing,
          model: selectedModel,
          tools: arm,
          think,
          code_mode: codeMode,
          attachment_ids: attachmentIds,
        },
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
            // The model switched projects (ws_cd) — sync the header live.
            if (t.name === 'ws_cd' && (t.exit === 0 || t.exit === null)) {
              api.getSettings().then((s) => setWorkspace({ root: s.workspace_root || '', project: s.active_project || '' })).catch(() => {})
            }
            // Artifact bridge: an .html file the model wrote/edited opens
            // (or refreshes) in the preview pane instead of flooding chat.
            // build_pptx reports its generated slide player as the path.
            if ((t.name === 'ws_write' || t.name === 'ws_edit' || t.name === 'build_pptx') && (t.exit === 0 || t.exit === null)) {
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

  async function closeEditor() {
    setEditorOpen(false)
    await api.saveSettings({ ide_open: false })
  }

  function openBrowser(url) {
    if (!editorOpen) {
      setEditorOpen(true)
      api.saveSettings({ ide_open: true })
    }
    setBrowserUrl(url)
    setBrowserHistory([url])
    setBrowserIndex(0)
  }

  function browserNavigate(url) {
    url = unwrapRedirect(url)
    setBrowserHistory((prev) => [...prev.slice(0, browserIndex + 1), url])
    setBrowserIndex(browserIndex + 1)
    setBrowserUrl(url)
  }

  // Links inside the pane's iframe are `target="_blank"`. pywebview's GTK
  // backend catches those in its `create` handler and calls this hook so the
  // page loads in the PANE instead of replacing the whole app.
  useEffect(() => {
    window.__su1raOpenInPane = (url) => {
      if (!url) return
      url = unwrapRedirect(url)
      setEditorOpen(true)
      setBrowserHistory((prev) => [...prev.slice(0, browserIndex + 1), url])
      setBrowserIndex(browserIndex + 1)
      setBrowserUrl(url)
    }
    return () => { delete window.__su1raOpenInPane }
  }, [browserIndex])

  function browserBack() {
    const ni = browserIndex - 1
    if (ni < 0) return
    setBrowserIndex(ni)
    setBrowserUrl(browserHistory[ni])
  }

  function browserForward() {
    const ni = browserIndex + 1
    if (ni >= browserHistory.length) return
    setBrowserIndex(ni)
    setBrowserUrl(browserHistory[ni])
  }

  function browserClose() {
    setBrowserUrl(null)
    if (artifact === null) setEditorOpen(false)
  }

  // Browser pane -> chat: inject the fetched page text as a user message so
  // the model summarizes it. Errors surface as a system note, not a crash.
  function summarizePage(page) {
    if (page.error) {
      pushSystem(`// could not summarize ${page.url}\n// ${page.error}`)
      return
    }
    const header = `Summarize this web page in under ~300 words. Focus on the main points; do not reproduce it verbatim.\n\n--- ${page.title || page.url} ---\n${page.url}\n\n`
    send(header + page.text, { forceArmed: false })
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
    if (!editorOpen) {
      setEditorOpen(true)
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
      if (!editorOpen) {
        setEditorOpen(true)
        api.saveSettings({ ide_open: true })
      }
      pushSystem(`// preview: ${res.path}`)
    } catch (err) {
      pushSystem(`// preview failed for ${path}: ${err.message}`)
    }
  }

  async function downloadArtifact(code, css, js, kind) {
    try {
      const res = await api.downloadArtifact(code, undefined, { css: css || undefined, js: js || undefined, kind: kind || undefined })
      pushSystem(`// artifact saved to ${res.path}`)
    } catch (err) {
      pushSystem(`// download failed: ${err.message}`)
    }
  }

  function loadToIde(code) {
    setArtifact(null)
    setArtifactPath(null)
    setEditorCode(code)
    if (!editorOpen) {
      setEditorOpen(true)
      api.saveSettings({ ide_open: true })
    }
    pushSystem(`// loaded ${code.split('\n').length} lines into the ide`)
  }

  function runInIde(code) {
    setArtifact(null)
    setArtifactPath(null)
    setEditorCode(code)
    if (!editorOpen) {
      setEditorOpen(true)
      api.saveSettings({ ide_open: true })
    }
    setRunSignal((s) => s + 1)
  }

  function sendEditorToChat() {
    editorRunSeenRef.current = editorOutput
    const { text, exitCode } = editorOutput
    const out = text
    const status = exitCode === null ? 'not run' : exitCode < 0 ? 'killed' : `exit ${exitCode}`
    const lang = (editorName.split('.').pop() || 'txt').toLowerCase()
    const parts = [
      'Here is the code currently in my editor:',
      '',
      '```' + lang,
      editorCode,
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
    document.body.classList.add('pane-resizing')
    let ended = false
    const onMove = (ev) => {
      if (ended) return
      // Belt-and-suspenders: if no button is held, this is a stale drag —
      // end it instead of chasing the mouse.
      if (ev.buttons !== undefined && ev.buttons !== 0 && (ev.buttons & 1) === 0) {
        onUp()
        return
      }
      const maxW = Math.max(280, Math.min(1200, window.innerWidth - 360))
      const next = Math.min(maxW, Math.max(280, window.innerWidth - ev.clientX))
      widthRef.current = next
      setEditorWidth(next)
    }
    const onUp = () => {
      if (ended) return
      ended = true
      document.body.classList.remove('pane-resizing')
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

  async function saveSettings({ ollamaUrl, systemPrompt, systemPromptScope, temperature, contextLength, accent: newAccent, sandboxTools: sandboxPref, sandboxBackend: sandboxBackendPref, loadoutCasualModel, loadoutCodeModel, loadoutCasualCtx, loadoutCodeCtx, loadoutCasualThink, bgBrightness: newBrightness, bgContrast: newContrast, engine: newEngine, engineVulkan: vulkanPref, workspaceRoot, activeProject }) {
    // Autosaved on every change (no Save button) — stay open, skip invalid
    // mid-typing values instead of failing the whole patch.
    const url = (ollamaUrl || '').trim()
    const urlOk = url.startsWith('http://') || url.startsWith('https://')
    const tempOk = temperature === undefined || Number.isFinite(temperature)
    // New chats follow the casual loadout ctx (falls back to the per-chat value).
    const newDefaultCtx = loadoutCasualCtx || contextLength
    // System prompt edits land in ONE place (scope): 'default' = the mode's
    // global default (build -> default_system_prompt/sysp.txt, casual ->
    // default_system_prompt_casual); 'chat' = the open chat's per-chat
    // override. Editing a default must never re-stamp the open chat, and a
    // per-chat edit must never touch the defaults.
    const spDefined = systemPrompt !== undefined
    const spToDefault = spDefined && systemPromptScope !== 'chat'
    const spToChat = spDefined && systemPromptScope === 'chat'
    await api.saveSettings({
      ...(urlOk ? { ollama_url: url } : {}),
      accent: newAccent,
      ...(sandboxPref === undefined ? {} : { sandbox_tools: sandboxPref }),
      ...(sandboxBackendPref === undefined ? {} : { sandbox_backend: sandboxBackendPref }),
      ...(spToDefault ? { [codeArmed ? 'default_system_prompt' : 'default_system_prompt_casual']: systemPrompt } : {}),
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
    if (sandboxBackendPref !== undefined) setSandboxBackend(sandboxBackendPref)
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
      system_prompt: spToDefault && codeArmed ? systemPrompt : chatDefaultsRef.current.system_prompt,
      temperature,
      context_length: newDefaultCtx,
      think: loadoutCasualThink !== undefined ? (loadoutCasualThink === 'on' ? 'on' : 'off') : chatDefaultsRef.current.think,
    }
    if (spToDefault && !codeArmed) setCasualSysp(systemPrompt)
    setStatus(await api.getStatus())
    setAccent(newAccent)
    if (newBrightness !== undefined) setBgBrightness(newBrightness)
    if (newContrast !== undefined) setBgContrast(newContrast)
    if (activeConversation) {
      const updated = await api.updateConversation(activeConversation.id, {
        ...(spToChat ? { system_prompt: systemPrompt } : {}),
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
      {dragActive && (
        <div className="drop-overlay">
          <div className="drop-overlay-inner">
            <span className="drop-overlay-title">[ drop files to attach ]</span>
            <span className="drop-overlay-sub">images · pdf · word · powerpoint · excel · text &amp; code</span>
          </div>
        </div>
      )}
      <div className="app">
      <main className="main">
        <header className="app-header pywebview-drag-region" onDoubleClick={onHeaderDouble}>
          <div className="brand-line">
            <Logo size={20} />
            <span className="brand">Su1ra</span>
            <span className="brand-ver">v0.3.2</span>
            <span className={`status-tag${status?.ok ? ' ok' : ''}`}>
              [{status?.ok ? 'ok' : 'offline'}]
            </span>
            <span style={{ flex: 1 }} />
            <WindowControls />
          </div>
          <div className="chat-meta">
            <span className="hash">#</span>
            {activeConversation?.title || 'no chat'}
            <span className="meta-model"> · {codeArmed ? 'build' : 'casual'} · model: {currentModel || 'none'} · think: {currentThink || 'auto'}</span>
          </div>
        </header>
        <ChatView messages={messages} status={status} streaming={streaming} showStats={showStats} onLoadToIde={loadToIde} onRunCode={runInIde} onDownloadArtifact={downloadArtifact} onOpenArtifact={openArtifact} onOllamaReady={refreshStatus} onResendFrom={resendFrom} />
        <Composer commands={COMMANDS} disabled={!currentModel} streaming={streaming} onSend={send} onStop={stop} codeArmed={codeArmed} vision={visionModel} attachments={pendingAttachments} onAddFiles={addFiles} onRemoveAttachment={removeAttachment} />
      </main>
      {editorOpen && (
        <>
          <div className="ide-resize" onPointerDown={startResize} />
          {artifact !== null || browserUrl !== null ? (
            <ArtifactPane
              width={editorWidth}
              code={artifact}
              path={artifactPath}
              tab={artifactTab}
              onTab={setArtifactTab}
              onClose={closeEditor}
              onDownload={() => downloadArtifact(artifact)}
              browserUrl={browserUrl}
              browserHistory={browserHistory}
              browserIndex={browserIndex}
              browserEngine={browserEngine}
              onBrowserNavigate={browserNavigate}
              onBrowserBack={browserBack}
              onBrowserForward={browserForward}
              onBrowserClose={browserClose}
              onBrowserEngineChange={setBrowserEngine}
              conversationId={activeId}
              onSummarize={summarizePage}
            />
          ) : (
            <EditorPane
              width={editorWidth}
              code={editorCode}
              filename={editorName}
              onCodeChange={setEditorCode}
              onFilenameChange={setEditorName}
              onClose={closeEditor}
              onResizeStart={startResize}
              onOutputChange={setEditorOutput}
              onSendToChat={sendEditorToChat}
              onPreview={(content, name) => {
                // editor "run" for html/svg: render the buffer in the preview pane
                setArtifact(content)
                setArtifactPath(null)
                setArtifactTab('preview')
                pushSystem(`// preview: ${name} (from editor)`)
              }}
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
            sandboxBackend={sandboxBackend}
            workspace={workspace}
            defaultSystemPrompt={chatDefaultsRef.current.system_prompt || ''}
            defaultSystemPromptCasual={casualSysp}
            mode={codeArmed ? 'build' : 'casual'}
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
