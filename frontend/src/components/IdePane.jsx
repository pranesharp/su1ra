import { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import * as api from '../api'
import { copyText } from '../clip'

function stripAnsi(text) {
  return text
    .replace(/\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)/g, '')
    .replace(/\x1B\[[0-9;?]*[ -/]*[@-~]/g, '')
}

function pushPlain(state, text) {
  let i = 0
  if (state.pendingCR && text.length) {
    state.pendingCR = false
    if (text[0] === '\n') {
      state.buf += state.line + '\n'
      state.line = ''
      i = 1
    } else {
      state.line = ''
    }
  }
  for (; i < text.length; i++) {
    const ch = text[i]
    if (ch === '\r') {
      if (text[i + 1] === '\n') {
        state.buf += state.line + '\n'
        state.line = ''
        i++
      } else if (i === text.length - 1) {
        state.pendingCR = true
        state.line = ''
      } else {
        state.line = ''
      }
    } else if (ch === '\n') {
      state.buf += state.line + '\n'
      state.line = ''
    } else if (ch === '\b') {
      state.line = state.line.slice(0, -1)
    } else if (ch !== '\x07') {
      state.line += ch
    }
  }
  const full = state.buf + state.line
  if (state.buf.length > 100000) state.buf = state.buf.slice(-80000)
  return full
}

export default function IdePane({ width, code, onCodeChange, onClose, onResizeStart, onOutputChange, onSendToChat, runSignal }) {
  const [lines, setLines] = useState([])
  const [running, setRunning] = useState(false)
  const [exitCode, setExitCode] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [runId, setRunId] = useState(null)
  const [inputText, setInputText] = useState('')
  const [termActive, setTermActive] = useState(false)
  const [plainOut, setPlainOut] = useState('')
  const [copyMark, setCopyMark] = useState(null)
  const controllerRef = useRef(null)
  const areaRef = useRef(null)
  const gutterRef = useRef(null)
  const outRef = useRef(null)
  const startRef = useRef(0)
  const hostRef = useRef(null)
  const termRef = useRef(null)
  const fitRef = useRef(null)
  const decoderRef = useRef(new TextDecoder())
  const plainRef = useRef({ buf: '', line: '' })
  const termModeRef = useRef(false)
  const runIdRef = useRef(null)
  const pendingRef = useRef([])

  const lineCount = code.split('\n').length

  useEffect(() => {
    if (outRef.current) outRef.current.scrollTop = outRef.current.scrollHeight
  }, [lines])

  useEffect(() => {
    if (!running) return
    startRef.current = Date.now()
    setElapsed(0)
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [running])

  useEffect(() => {
    return () => controllerRef.current?.abort()
  }, [])

  useEffect(() => {
    const text = termActive ? plainOut : lines.map((l) => l.text).join('\n')
    onOutputChange && onOutputChange({ text, exitCode })
  }, [lines, plainOut, exitCode, termActive])

  useEffect(() => {
    if (!hostRef.current) return
    const ro = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        try {
          fitRef.current?.fit()
        } catch {}
      })
    })
    ro.observe(hostRef.current)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    requestAnimationFrame(() => {
      try {
        fitRef.current?.fit()
      } catch {}
    })
  }, [width])

  // The terminal canvas keeps its own colors (transparent bg, so it sits on
  // --surface): follow the html data-mode that applyBackground maintains and
  // flip the foreground when brightness crosses into light mode.
  useEffect(() => {
    function applyTermMode() {
      const term = termRef.current
      if (!term) return
      const light = document.documentElement.dataset.mode === 'light'
      term.options.theme = {
        ...term.options.theme,
        foreground: light ? '#2b2620' : '#c6c6cc',
        cursorAccent: light ? '#f0ede4' : '#101014',
        selectionBackground: light ? '#b9b09a66' : '#3a3a4166',
      }
    }
    applyTermMode()
    const obs = new MutationObserver(applyTermMode)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-mode'] })
    return () => obs.disconnect()
  }, [])

  const runRef = useRef()
  const runningRef = useRef(false)
  const lastSignalRef = useRef(runSignal)

  useEffect(() => {
    runRef.current = run
  })

  useEffect(() => {
    runningRef.current = running
  }, [running])

  useEffect(() => {
    if (runSignal !== lastSignalRef.current) {
      lastSignalRef.current = runSignal
      if (!runningRef.current) runRef.current?.()
    }
  }, [runSignal])

  function syncScroll() {
    if (gutterRef.current && areaRef.current) {
      gutterRef.current.scrollTop = areaRef.current.scrollTop
    }
  }

  function ensureTerm() {
    if (termRef.current) return termRef.current
    const style = getComputedStyle(document.documentElement)
    const term = new Terminal({
      fontFamily: style.getPropertyValue('--mono').trim() || 'monospace',
      fontSize: 12.5,
      lineHeight: 1.35,
      cursorBlink: true,
      scrollback: 5000,
      theme: {
        background: '#00000000',
        foreground: '#c6c6cc',
        cursor: style.getPropertyValue('--accent').trim() || '#bf264a',
        cursorAccent: '#101014',
        selectionBackground: '#3a3a4166',
      },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(hostRef.current)
    try {
      fit.fit()
    } catch {}
    term.onData((data) => {
      if (termModeRef.current && runningRef.current && runIdRef.current) {
        api.sendRunInput(runIdRef.current, data).catch(() => {})
      }
    })
    termRef.current = term
    fitRef.current = fit
    return term
  }

  function openTerm() {
    const term = ensureTerm()
    if (pendingRef.current.length) {
      pendingRef.current.forEach((bytes) => term.write(bytes))
      pendingRef.current = []
    }
    term.focus()
  }

  function run() {
    if (running) {
      if (termModeRef.current) {
        api.sendRunInput(runIdRef.current, '\x03').catch(() => {})
        return
      }
      controllerRef.current?.abort()
      setRunning(false)
      return
    }
    setLines([])
    setExitCode(null)
    setRunId(null)
    runIdRef.current = null
    setInputText('')
    setPlainOut('')
    plainRef.current = { buf: '', line: '' }
    decoderRef.current = new TextDecoder()
    termModeRef.current = false
    termRef.current?.clear()
    setRunning(true)
    const controller = new AbortController()
    controllerRef.current = controller
    api.streamRun(
      { code, language: 'python' },
      {
        onRun: (id, isTerm) => {
          setRunId(id)
          runIdRef.current = id
          termModeRef.current = !!isTerm
          setTermActive(!!isTerm)
          if (isTerm) {
            requestAnimationFrame(() => openTerm())
          }
        },
        onTerm: (b64) => {
          const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
          const text = decoderRef.current.decode(bytes, { stream: true })
          if (termRef.current) termRef.current.write(bytes)
          else pendingRef.current.push(bytes)
          const plain = pushPlain(plainRef.current, stripAnsi(text))
          setPlainOut(plain)
        },
        onLine: (stream, text) => setLines((prev) => [...prev, { stream, text }]),
        onExit: (code) => {
          setRunning(false)
          setExitCode(code)
          controllerRef.current = null
        },
        onError: (error) => {
          setLines((prev) => [...prev, { stream: 'stderr', text: error }])
          setRunning(false)
          controllerRef.current = null
        },
      },
      controller.signal,
    ).catch(() => {})
  }

  function sendInput() {
    if (!runId || !inputText) return
    const text = inputText
    setInputText('')
    setLines((prev) => [...prev, { stream: 'stdin', text }])
    api.sendRunInput(runId, text).catch((err) => {
      setLines((prev) => [...prev, { stream: 'stderr', text: err.message }])
    })
  }

  async function copyOutput() {
    const text = termActive ? plainOut : lines.map((l) => l.text).join('\n')
    if (!text) return
    const ok = await copyText(text)
    setCopyMark(ok ? 'copied' : 'failed')
    setTimeout(() => setCopyMark(null), 1500)
  }

  function handleKeyDown(e) {
    if (e.key === 'Tab') {
      e.preventDefault()
      const el = areaRef.current
      if (!el) return
      const { selectionStart, selectionEnd, value } = el
      const next = value.slice(0, selectionStart) + '  ' + value.slice(selectionEnd)
      onCodeChange(next)
      requestAnimationFrame(() => {
        el.selectionStart = el.selectionEnd = selectionStart + 2
      })
    }
  }

  const status = running
    ? `// running... ${elapsed}s`
    : exitCode === null
      ? '// ready'
      : exitCode < 0
        ? '// killed'
        : `// exit ${exitCode}`

  return (
    <aside className="ide-pane" style={{ width }}>
      <div className="ide-head">
        <span className="hash">#</span>
        <span className="ide-title">ide</span>
        <span style={{ flex: 1 }} />
        <button className="term-btn" onClick={copyOutput}>
          {copyMark === 'copied' ? 'copied' : copyMark === 'failed' ? 'copy failed' : 'copy'}
        </button>
        <button className="term-btn" onClick={onSendToChat}>
          send to chat
        </button>
        <button className="term-btn" onClick={run}>
          {running ? 'stop' : 'run'}
        </button>
        <button className="term-btn" onClick={onClose}>
          close
        </button>
      </div>
      <div className="ide-editor">
        <div className="ide-gutter" ref={gutterRef}>
          {Array.from({ length: lineCount }, (_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>
        <textarea
          ref={areaRef}
          className="ide-code"
          value={code}
          onChange={(e) => onCodeChange(e.target.value)}
          onScroll={syncScroll}
          onKeyDown={handleKeyDown}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          wrap="off"
        />
      </div>
      <div className={`ide-term${termActive ? ' active' : ''}`} ref={hostRef} onClick={() => termRef.current?.focus()} />
      {!termActive && (
        <pre className="ide-out" ref={outRef}>
          {lines.map((l, i) => (
            <div key={i} className={`ide-line${l.stream === 'stderr' ? ' err' : ''}${l.stream === 'stdin' ? ' in' : ''}`}>
              {l.text}
            </div>
          ))}
        </pre>
      )}
      {running && !termActive && (
        <div className="ide-input">
          <span className="ide-input-prompt">›</span>
          <input
            className="ide-input-field"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                sendInput()
              }
            }}
            placeholder="type input and press enter"
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
          />
        </div>
      )}
      <div className="ide-status">{status}</div>
    </aside>
  )
}
