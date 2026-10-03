import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

function displayizeSingleLine(seg) {
  return seg
    .split('\n')
    .map((line) => {
      const t = line.trim()
      if (t.length > 4 && t.startsWith('$$') && t.endsWith('$$') && (t.match(/\$\$/g) || []).length === 2) {
        return `$$\n${t.slice(2, -2)}\n$$`
      }
      return line
    })
    .join('\n')
}

function convertMathDelims(text) {
  return text
    .split(/```/)
    .map((seg, i) =>
      i % 2 === 1
        ? seg
        : displayizeSingleLine(
            seg
              .replace(/\\\((.+?)\\\)/gs, (_, m) => `$${m}$`)
              .replace(/\\\[(.+?)\\\]/gs, (_, m) => `$$$$${m}$$$$`),
          ),
    )
    .join('```')
}
import { formatStats } from '../statsFormat'

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

function ToolBlock({ name, code, onLoadToIde }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="tool">
      <div className="tool-label" onClick={() => setOpen((v) => !v)}>
        {open ? '▾' : '▸'} tool: {name} · {code.split('\n').length} lines
      </div>
      {open && (
        <div className="tool-code">
          <button className="tool-load" onClick={() => onLoadToIde && onLoadToIde(code)}>
            [ load to ide ]
          </button>
          <pre>
            <code>{code}</code>
          </pre>
        </div>
      )}
    </div>
  )
}

function ToolOutputBlock({ content }) {
  const lines = content.split('\n')
  const [open, setOpen] = useState(lines.length <= 12)
  return (
    <div className="tool">
      <div className="tool-label" onClick={() => setOpen((v) => !v)}>
        {open ? '▾' : '▸'} tool output · {lines.length} lines
      </div>
      {open && <pre className="tool-out">{content}</pre>}
    </div>
  )
}

function lastHtmlBlock(text) {
  const blocks = [...text.matchAll(/```html\n([\s\S]*?)```/g)]
  return blocks.length ? blocks[blocks.length - 1][1].replace(/\n$/, '') : null
}

function Linkified({ text }) {
  const parts = text.split(/(https?:\/\/[^\s)]+)/g)
  return (
    <pre className="sys-out">
      {parts.map((p, i) =>
        /^https?:\/\//.test(p) ? (
          <a key={i} className="chat-link" href={p} target="_blank" rel="noreferrer">
            {p}
          </a>
        ) : (
          p
        ),
      )}
    </pre>
  )
}

export function splitThinking(content) {
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

function AssistantContent({ content, toolCalls, streaming, onLoadToIde, onRunCode }) {
  if (!content && !(toolCalls || []).length) return streaming ? <span className="cursor" /> : null
  const parts = splitThinking(content)
  return (
    <>
      {parts.map((p, i) =>
        p.think ? (
          <ThinkBlock key={i} text={p.text} />
        ) : (
          <div key={i} className="md">
            <Markdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
              components={{
                code({ className, children, ...props }) {
                  const text = String(children).replace(/\n$/, '')
                  const lang = /language-(\w+)/.exec(className || '')?.[1]
                  const isBlock = className?.includes('language-') || text.includes('\n')
                  if (!isBlock) return <code className={className} {...props}>{children}</code>
                  return (
                    <div className="code-block">
                      <div className="code-head">
                        <span className="code-lang">{lang || 'text'}</span>
                        {lang === 'python' && (
                          <button className="code-run" onClick={() => onRunCode && onRunCode(text)}>
                            [ run code ]
                          </button>
                        )}
                      </div>
                      <pre>
                        <code className={className} {...props}>{children}</code>
                      </pre>
                    </div>
                  )
                },
              }}
            >
              {convertMathDelims(p.text)}
            </Markdown>
          </div>
        ),
      )}
      {(toolCalls || []).map((tc, i) => (
        <ToolBlock
          key={`tool-${i}`}
          name={tc?.function?.name || 'tool'}
          code={tc?.function?.arguments?.code || ''}
          onLoadToIde={onLoadToIde}
        />
      ))}
      {streaming && <span className="cursor" />}
    </>
  )
}

export default function ChatView({ messages, status, streaming, showStats, onLoadToIde, onRunCode, onDownloadArtifact, onOpenArtifact }) {
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
                <Linkified text={m.content} />
              </div>
            ) : m.role === 'tool' ? (
              <div key={m.id} className="msg tool-msg">
                <ToolOutputBlock content={m.content} />
              </div>
            ) : (
              <div key={m.id} className="msg assistant">
                <div className="who">── assistant ─────────────────────────────</div>
                <AssistantContent content={m.content} toolCalls={m.tool_calls} streaming={streaming} onLoadToIde={onLoadToIde} onRunCode={onRunCode} />
                {onDownloadArtifact && /```html\n/.test(m.content || '') && !streaming && (
                  <span className="artifact-actions">
                    <button className="code-run artifact-dl" onClick={() => onOpenArtifact(lastHtmlBlock(m.content))}>
                      [ open artifact ]
                    </button>
                    <button className="code-run artifact-dl" onClick={() => onDownloadArtifact(lastHtmlBlock(m.content))}>
                      [ download artifact ]
                    </button>
                  </span>
                )}
                {m.stats && showStats && (
                  <pre className="stats-out">{formatStats(m.stats)}</pre>
                )}
              </div>
            ),
          )
        )}
      </div>
    </div>
  )
}
