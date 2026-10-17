import { useEffect, useRef, useState } from 'react'
import SysMonitor from './SysMonitor'

const DOC_ACCEPT =
  '.pdf,.docx,.pptx,.xlsx,.xlsm,.txt,.md,.csv,.tsv,.json,.yaml,.yml,.xml,.html,.htm,.css,' +
  '.py,.js,.jsx,.ts,.tsx,.c,.h,.cpp,.hpp,.cs,.java,.go,.rs,.rb,.php,.sh,.sql,.r,.kt,.swift,.lua'

function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 17h6" />
    </svg>
  )
}

function ImgIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="8.5" cy="9.5" r="1.5" />
      <path d="M21 16l-5-5-4 4-2-2-7 7" />
    </svg>
  )
}

// Tiny accent sine wave shown while the model works (streaming or in the
// tool loop) — mounted only when `streaming` is true, gone on [ send ].
function SineWave() {
  return (
    <div className="sine-wave" aria-hidden="true">
      <svg viewBox="0 0 72 14" width="72" height="14" fill="none">
        <path
          className="sine-path"
          d="M0 7 Q 4.5 1, 9 7 T 18 7 T 27 7 T 36 7 T 45 7 T 54 7 T 63 7 T 72 7"
          stroke="var(--accent)"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    </div>
  )
}

export default function Composer({
  commands = [],
  disabled,
  streaming,
  onSend,
  onStop,
  codeArmed,
  vision = false,
  attachments = [],
  onAddFiles,
  onRemoveAttachment,
  pendingRequest,
  cartCount = 0,
  onFindResource,
  onSendCart,
  onSkipCart,
}) {
  const [text, setText] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const areaRef = useRef(null)
  const imgRef = useRef(null)
  const docRef = useRef(null)
  const pickerRef = useRef(null)

  const isCmdTyping = /^\/\w*$/.test(text)
  const suggestions = isCmdTyping ? commands.filter((c) => c.cmd.startsWith(text)) : []

  function resize() {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 208) + 'px'
  }

  useEffect(() => {
    resize()
  }, [text])

  // Close the [+] picker when clicking anywhere outside it.
  useEffect(() => {
    if (!pickerOpen) return
    function onDown(e) {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) setPickerOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [pickerOpen])

  function submit() {
    if (streaming) return
    const value = text.trim()
    if (!value && attachments.length === 0) return
    onSend(value)
    setText('')
    setPickerOpen(false)
    requestAnimationFrame(() => {
      if (areaRef.current) areaRef.current.style.height = 'auto'
    })
  }

  function complete() {
    if (suggestions.length > 0) {
      setText(suggestions[0].cmd + ' ')
      requestAnimationFrame(resize)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    } else if (e.key === 'Tab' && suggestions.length > 0) {
      e.preventDefault()
      complete()
    } else if (e.key === 'Escape') {
      setText('')
      setPickerOpen(false)
    }
  }

  function pickFiles(fileList) {
    const files = Array.from(fileList || [])
    if (files.length && onAddFiles) onAddFiles(files)
  }

  function handlePaste(e) {
    if (!vision) return
    const items = e.clipboardData?.items
    if (!items) return
    const files = []
    for (const it of items) {
      if (it.kind === 'file' && it.type.startsWith('image/')) {
        const f = it.getAsFile()
        if (f) files.push(f)
      }
    }
    if (files.length) {
      e.preventDefault()
      pickFiles(files)
    }
  }

  return (
    <div className="composer-wrap">
      {pendingRequest && (
        <div className="resource-strip">
          <div className="resource-strip-head">! resources requested — model is waiting</div>
          <ul className="resource-strip-items">
            {pendingRequest.items.map((it, i) => (
              <li key={i} className="resource-strip-item">
                <span className="rs-topic" title={[it.why, it.search_hint].filter(Boolean).join(' · ') || it.topic}>
                  {it.topic}
                </span>
                <button
                  className="btn-solid"
                  title={it.why ? `find: ${it.search_hint || it.topic}` : 'open the browser pane with this search'}
                  onClick={() => onFindResource?.(it.search_hint || it.topic)}
                >
                  find in /web
                </button>
              </li>
            ))}
          </ul>
          <div className="resource-strip-actions">
            {cartCount > 0 ? (
              <button className="btn-solid" onClick={onSendCart}>
                send cart ({cartCount})
              </button>
            ) : (
              <span className="rs-note">// cart empty — find above, then add to cart in the pane</span>
            )}
            <button className="btn-solid ghost" title="decline — the model proceeds without the material" onClick={onSkipCart}>
              skip
            </button>
          </div>
        </div>
      )}
      {streaming && <SineWave />}
      {attachments.length > 0 && (
        <div className="attach-strip">
          {attachments.map((a, i) => (
            <div className="attach-chip" key={a.id ?? a.localId ?? i}>
              <div className="attach-title">
                {a.kind === 'document' ? `[doc ${a.docIndex ?? i + 1}]` : `[image ${a.imgIndex ?? i + 1}]`}
              </div>
              {a.kind === 'document' ? (
                <div className="attach-doc" title={a.filename}>
                  <DocIcon />
                  <span className="attach-doc-name">{a.filename}</span>
                </div>
              ) : (
                <img className="attach-thumb" src={a.url} alt={a.filename || `image ${i + 1}`} />
              )}
              <button
                className="attach-remove"
                title="Remove"
                onClick={() => onRemoveAttachment?.(a)}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <div
        className={`composer${disabled && !text.startsWith('/') ? ' disabled' : ''}`}
      >
        <div className="attach-picker" ref={pickerRef}>
          <button
            className={`term-btn attach-btn${pickerOpen ? ' open' : ''}`}
            title="Attach a file"
            onClick={() => setPickerOpen((v) => !v)}
          >
            [ + ]
          </button>
          {pickerOpen && (
            <div className="attach-menu">
              {vision && (
                <button
                  className="attach-opt"
                  title="Attach image"
                  onClick={() => {
                    imgRef.current?.click()
                    setPickerOpen(false)
                  }}
                >
                  <ImgIcon />
                </button>
              )}
              <button
                className="attach-opt"
                title="Attach document"
                onClick={() => {
                  docRef.current?.click()
                  setPickerOpen(false)
                }}
              >
                <DocIcon />
              </button>
            </div>
          )}
          <input
            ref={imgRef}
            type="file"
            accept="image/*"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => {
              pickFiles(e.target.files)
              e.target.value = ''
            }}
          />
          <input
            ref={docRef}
            type="file"
            accept={DOC_ACCEPT}
            multiple
            style={{ display: 'none' }}
            onChange={(e) => {
              pickFiles(e.target.files)
              e.target.value = ''
            }}
          />
        </div>
        <span className="prompt-char">❯</span>
        <textarea
          ref={areaRef}
          rows={1}
          value={text}
          placeholder={streaming ? '' : disabled ? '// select a model — /models' : '// send a message — /help for commands'}
          onChange={(e) => {
            setText(e.target.value)
            resize()
          }}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => e.preventDefault()}
        />
        {streaming ? (
          <button className="term-btn stop" title="Stop generating" onClick={onStop}>
            [ stop ]
          </button>
        ) : (
          <button
            className="term-btn accent send"
            title="Send"
            disabled={!text.trim() && attachments.length === 0}
            onClick={submit}
          >
            [ send ]
          </button>
        )}
        {suggestions.length > 0 && (
          <div className="cmd-suggest">
            {suggestions.map((c) => (
              <div
                key={c.cmd}
                className="cmd-item"
                onClick={() => {
                  setText(c.cmd + ' ')
                  areaRef.current?.focus()
                }}
              >
                <span className="cmd-name">{c.cmd}</span>
                <span className="cmd-desc">{c.desc}</span>
              </div>
            ))}
            <div className="cmd-foot">tab to complete · esc to clear</div>
          </div>
        )}
      </div>
      <div className="composer-foot">
        <SysMonitor />
        <div className="composer-hint">
          {codeArmed ? '// tools armed — files + python enabled · ' : ''}
          {vision ? 'drop or paste images · ' : ''}
          enter to send · shift+enter for newline · /help for commands
        </div>
      </div>
    </div>
  )
}
