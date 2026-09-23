import { useEffect, useRef, useState } from 'react'
import * as api from './api'
import ChatView from './components/ChatView.jsx'
import Composer from './components/Composer.jsx'
import SettingsModal from './components/SettingsModal.jsx'

const COMMANDS = [
  { cmd: '/help', desc: 'show available commands' },
  { cmd: '/models', desc: 'list models — /models <name|n> to select' },
  { cmd: '/newchat', desc: 'start a new conversation' },
  { cmd: '/chats', desc: 'list chats — /chats <n|id> to open' },
  { cmd: '/delchat', desc: 'delete a chat — /delchat <n|id>' },
  { cmd: '/settings', desc: 'open settings' },
  { cmd: '/eject', desc: 'shut down the ollama server instantly' },
  { cmd: '/connect', desc: 'start / reconnect the ollama server' },
]

export default function App() {
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [models, setModels] = useState([])
  const [status, setStatus] = useState(null)
  const [selectedModel, setSelectedModel] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const abortRef = useRef(null)
  const idRef = useRef(1000)

  useEffect(() => {
    async function boot() {
      const [statusRes, modelsRes, convsRes] = await Promise.all([
        api.getStatus(),
        api.getModels(),
        api.getConversations(),
      ])
      setStatus(statusRes)
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

  const activeConversation = conversations.find((c) => c.id === activeId) || null
  const blocked = streaming

  function pushSystem(content) {
    setMessages((prev) => [...prev, { id: ++idRef.current, role: 'system', content }])
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

    pushSystem(`${echo}\n\n// unknown command: ${cmd} — try /help`)
  }

  async function send(content) {
    const trimmed = content.trim()
    if (!trimmed || streaming) return
    if (trimmed.startsWith('/')) {
      await handleCommand(trimmed)
      return
    }
    if (!selectedModel) return
    let convId = activeId
    if (!activeConversation) {
      const conversation = await api.createConversation({ model: selectedModel })
      convId = conversation.id
      setConversations((prev) => [conversation, ...prev])
      setActiveId(convId)
    }
    const userMsg = { id: ++idRef.current, role: 'user', content: trimmed }
    const assistantMsg = { id: ++idRef.current, role: 'assistant', content: '' }
    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let partial = ''
    try {
      await api.streamChat(
        { conversation_id: convId, content: trimmed, model: selectedModel },
        {
          onDelta: (delta) => {
            partial += delta
            setMessages((prev) =>
              prev.map((m, i) => (i === prev.length - 1 ? { ...m, content: m.content + delta } : m)),
            )
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
    const convs = await api.getConversations()
    setConversations(convs.conversations)
  }

  function stop() {
    abortRef.current?.abort()
  }

  async function saveSettings({ ollamaUrl, systemPrompt, temperature, contextLength }) {
    await api.saveSettings({ ollama_url: ollamaUrl })
    setStatus(await api.getStatus())
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
            <span className="brand-mark" />
            <span className="brand">Su1ra</span>
            <span className="brand-ver">v0.1.0</span>
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
        <ChatView messages={messages} status={status} streaming={streaming} />
        <Composer commands={COMMANDS} disabled={!currentModel} streaming={streaming} onSend={send} onStop={stop} />
      </main>
      {settingsOpen && (
        <SettingsModal
          status={status}
          conversation={activeConversation}
          onSave={saveSettings}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  )
}
