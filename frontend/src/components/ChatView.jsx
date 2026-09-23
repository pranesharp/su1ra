import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function ThinkBlock({ text }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="think">
      <div className="think-label" onClick={() => setOpen((v) => !v)}>
        {open ? '▾' : '▸'} thinking · {text.trim().length} chars
      </div>
      {open && <div className="think-text">{text.trim()}</div>}
    </div>
  )
}

function splitThinking(content) {
  const parts = []
  let rest = content
  let inThink = false
  while (rest) {
    const openIdx = rest.indexOf('<think>')
    const closeIdx = rest.indexOf('</think>')
    let idx = -1
    if (inThink) idx = closeIdx
    else idx = openIdx === -1 ? -1 : closeIdx === -1 ? openIdx : Math.min(openIdx, closeIdx)
    if (idx === -1) {
      if (rest.trim()) parts.push({ think: inThink, text: rest })
      break
    }
    if (idx > 0) parts.push({ think: inThink, text: rest.slice(0, idx) })
    const tagLen = inThink ? 8 : 7
    rest = rest.slice(idx + tagLen)
    inThink = !inThink
  }
  return parts
}

function AssistantContent({ content, streaming }) {
  if (!content) return streaming ? <span className="cursor" /> : null
  const parts = splitThinking(content)
  return (
    <>
      {parts.map((p, i) =>
        p.think ? (
          <ThinkBlock key={i} text={p.text} />
        ) : (
          <div key={i} className="md">
            <Markdown remarkPlugins={[remarkGfm]}>{p.text}</Markdown>
          </div>
        ),
      )}
      {streaming && <span className="cursor" />}
    </>
  )
}

export default function ChatView({ messages, status, streaming }) {
  const scrollRef = useRef(null)
  const stickRef = useRef(true)

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages])

  return (
    <div className="chat" ref={scrollRef} onScroll={handleScroll}>
      <div className="chat-inner">
        {messages.length === 0 ? (
          <div className="empty">
            <h1>chat with your local models<span className="cursor" /></h1>
            <p>// everything runs on your machine</p>
            <p>// type /help for commands, or just start typing</p>
            {status && !status.ok && (
              <p className="warn">// cannot reach the ollama server — /settings to fix the url</p>
            )}
          </div>
        ) : (
          messages.map((m) =>
            m.role === 'user' ? (
              <div key={m.id} className="msg user">
                <span className="prompt-char">❯</span>
                <div className="user-text">{m.content}</div>
              </div>
            ) : m.role === 'system' ? (
              <div key={m.id} className="msg system">
                <pre className="sys-out">{m.content}</pre>
              </div>
            ) : (
              <div key={m.id} className="msg assistant">
                <div className="who">── assistant ─────────────────────────────</div>
                <AssistantContent content={m.content} streaming={streaming} />
              </div>
            ),
          )
        )}
      </div>
    </div>
  )
}
