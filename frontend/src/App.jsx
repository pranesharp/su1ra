import { useEffect, useRef, useState } from 'react'
import * as api from './api'
import { applyAccent, DEFAULT_ACCENT } from './theme'
import ChatView, { splitThinking } from './components/ChatView.jsx'
import Composer from './components/Composer.jsx'
import Logo from './components/Logo.jsx'
import SettingsModal from './components/SettingsModal.jsx'
import IdePane from './components/IdePane.jsx'
import ArtifactPane from './components/ArtifactPane.jsx'

const COMMANDS = [
  { cmd: '/help', desc: 'show available commands' },
  { cmd: '/models', desc: 'list models — /models <name|n> to select, /models pull <name> to download, /models get [query] to browse' },
  { cmd: '/newchat', desc: 'start a new conversation' },
  { cmd: '/chats', desc: 'list chats — /chats <n|id> to open' },
  { cmd: '/delchat', desc: 'delete a chat — /delchat <n|id>' },
  { cmd: '/settings', desc: 'open settings' },
  { cmd: '/eject', desc: 'shut down the ollama server instantly' },
  { cmd: '/connect', desc: 'start / reconnect the ollama server' },
  { cmd: '/stats', desc: 'toggle per-reply performance stats' },
  { cmd: '/code', desc: 'toggle code mode — the model may run code; /code <msg> arms one message' },
  { cmd: '/ide', desc: 'toggle the python ide pane' },
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
  const [selectedModel, setSelectedModel] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [accent, setAccent] = useState(DEFAULT_ACCENT)
  const [showStats, setShowStats] = useState(false)
  const [ideOpen, setIdeOpen] = useState(false)
  const [ideWidth, setIdeWidth] = useState(460)
  const [ideCode, setIdeCode] = useState(STARTER_CODE)
  const [ideOutput, setIdeOutput] = useState({ text: '', exitCode: null })
  const [artifact, setArtifact] = useState(null)
  const [artifactTab, setArtifactTab] = useState('preview')
  const [codeArmed, setCodeArmed] = useState(false)
  const [sandboxTools, setSandboxTools] = useState(true)
  const abortRef = useRef(null)
  const modelPullRef = useRef(null)
  const pendingToolRef = useRef(null)
  const ideRunSeenRef = useRef(null)
  const [runSignal, setRunSignal] = useState(0)
  const idRef = useRef(1000)
  const widthRef = useRef(460)
  const moveRef = useRef(null)
  const upRef = useRef(null)

  useEffect(() => {
    applyAccent(accent)
  }, [accent])

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
      setShowStats(settingsRes.show_stats === true)
      setIdeOpen(settingsRes.ide_open === true)
      setIdeWidth(typeof settingsRes.ide_width === 'number' ? settingsRes.ide_width : 460)
      setSandboxTools(settingsRes.sandbox_tools !== false)
      setModels(modelsRes.models)
      setConversations(convsRes.conversations)
      if (convsRes.conversations.length > 0) {
        const detail = await api.getConversation(convsRes.conversations[0].id)
        if (detail) {
          setActiveId(detail.conversation.id)
          setMessages(detail.messages)
          setSelectedModel(detail.conversation.model || '')
        }
      }
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
    const conversation = await api.createConversation({ model: selectedModel })
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
          `${echo}\n\n${lines.join('\n')}\n\n// select with: /models <name or number>`,
        )
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
      const conversation = resolveConversation(arg)
      if (!conversation) {
        pushSystem(`${echo}\n\n// no conversation #${arg} — try /chats`)
        return
      }
      await deleteConversation(conversation.id)
      pushSystem(`${echo}\n\n// deleted [${conversation.id}] ${conversation.title || 'new chat'}`)
      return
    }

    if (cmd === '/settings') {
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
          ? `// ollama started — connected to ${res.url}`
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

    if (cmd === '/ide') {
      const next = !ideOpen
      setIdeOpen(next)
      await api.saveSettings({ ide_open: next })
      const line = next ? '// ide pane: on' : '// ide pane: off'
      pushSystem(`${echo}\n\n${line}`)
      return
    }

    if (cmd === '/code') {
      const rest = arg
      if (rest) {
        pushSystem(`${echo}\n\n// one-shot: tools armed for this message`)
        await send(rest, { forceArmed: true })
      } else {
        const next = !codeArmed
        setCodeArmed(next)
        pushSystem(
          `${echo}\n\n${next ? '// code mode: on — the model may run code (persists until /code again, off on restart)' : '// code mode: off'}`,
        )
      }
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
    const arm = opts.forceArmed === true || codeArmed || /```python\n/.test(outgoing)
    if (!selectedModel) return
    let convId = activeId
    if (!activeConversation) {
      const conversation = await api.createConversation({ model: selectedModel })
      convId = conversation.id
      setConversations((prev) => [conversation, ...prev])
      setActiveId(convId)
    }
    const userMsg = { id: ++idRef.current, role: 'user', content: outgoing }
    const assistantMsg = { id: ++idRef.current, role: 'assistant', content: '' }
    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let partial = ''
    let replyStats = null
    try {
      await api.streamChat(
        { conversation_id: convId, content: outgoing, model: selectedModel, tools: arm },
        {
          onDelta: (delta) => {
            partial += delta
            setMessages((prev) =>
              prev.map((m, i) => (i === prev.length - 1 ? { ...m, content: m.content + delta } : m)),
            )
          },
          onStats: (s) => {
            replyStats = s
            setMessages((prev) =>
              prev.map((m, i) => (i === prev.length - 1 ? { ...m, stats: s } : m)),
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
              const next = base.map((m, i) =>
                i === base.length - 1 && m.role === 'assistant'
                  ? {
                      ...m,
                      content: t.replaces_text ? '' : m.content,
                      tool_calls: [
                        ...(m.tool_calls || []),
                        { function: { name: t.name, arguments: { code: t.code } } },
                      ],
                    }
                  : m,
              )
              next.push({ id: t.id, role: 'tool', content: t.output })
              next.push({ id: nextAssistantId, role: 'assistant', content: '' })
              return next
            })
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

  function openArtifact(code) {
    setArtifact(code)
    setArtifactTab('preview')
    if (!ideOpen) {
      setIdeOpen(true)
      api.saveSettings({ ide_open: true })
    }
  }

  async function downloadArtifact(code) {
    try {
      const res = await api.downloadArtifact(code)
      pushSystem(`// artifact saved to ${res.path}`)
    } catch (err) {
      pushSystem(`// download failed: ${err.message}`)
    }
  }

  function loadToIde(code) {
    setArtifact(null)
    setIdeCode(code)
    if (!ideOpen) {
      setIdeOpen(true)
      api.saveSettings({ ide_open: true })
    }
    pushSystem(`// loaded ${code.split('\n').length} lines into the ide`)
  }

  function runInIde(code) {
    setArtifact(null)
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
    e.preventDefault()
    const onMove = (ev) => {
      const next = Math.min(1200, Math.max(280, window.innerWidth - ev.clientX))
      widthRef.current = next
      setIdeWidth(next)
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      moveRef.current = null
      upRef.current = null
      api.saveSettings({ ide_width: widthRef.current })
    }
    moveRef.current = onMove
    upRef.current = onUp
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  async function saveSettings({ ollamaUrl, systemPrompt, temperature, contextLength, accent: newAccent, sandboxTools: sandboxPref }) {
    await api.saveSettings({ ollama_url: ollamaUrl, accent: newAccent, ...(sandboxPref === undefined ? {} : { sandbox_tools: sandboxPref }) })
    setStatus(await api.getStatus())
    setAccent(newAccent)
    if (activeConversation) {
      const updated = await api.updateConversation(activeConversation.id, {
        system_prompt: systemPrompt,
        temperature,
        context_length: contextLength,
      })
      if (updated) {
        setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
      }
    }
    setSettingsOpen(false)
  }

  const currentModel = activeConversation?.model || selectedModel

  return (
    <div className="app">
      <main className="main">
        <header className="app-header">
          <div className="brand-line">
            <Logo size={20} />
            <span className="brand">Su1ra</span>
            <span className="brand-ver">v0.2.0</span>
            <span className={`status-tag${status?.ok ? ' ok' : ''}`}>
              [{status?.ok ? 'ok' : 'offline'}]
            </span>
          </div>
          <div className="chat-meta">
            <span className="hash">#</span>
            {activeConversation?.title || 'no chat'}
            <span className="meta-model"> · model: {currentModel || 'none'}</span>
          </div>
        </header>
        <ChatView messages={messages} status={status} streaming={streaming} showStats={showStats} onLoadToIde={loadToIde} onRunCode={runInIde} onDownloadArtifact={downloadArtifact} onOpenArtifact={openArtifact} />
        <Composer commands={COMMANDS} disabled={!currentModel} streaming={streaming} onSend={send} onStop={stop} codeArmed={codeArmed} />
      </main>
      {ideOpen && (
        <>
          <div className="ide-resize" onMouseDown={startResize} />
          {artifact !== null ? (
            <ArtifactPane
              width={ideWidth}
              code={artifact}
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
            accent={accent}
            sandboxTools={sandboxTools}
            onSave={saveSettings}
            onClose={() => setSettingsOpen(false)}
            onModelsChanged={() => api.getModels().then((r) => setModels(r.models))}
          />
      )}
    </div>
  )
}
