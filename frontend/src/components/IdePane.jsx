import { useEffect, useRef, useState } from 'react'
import * as api from '../api'

export default function IdePane({ width, code, onCodeChange, onClose, onResizeStart, onOutputChange, onSendToChat, runSignal }) {
  const [lines, setLines] = useState([])
  const [running, setRunning] = useState(false)
  const [exitCode, setExitCode] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [runId, setRunId] = useState(null)
  const [inputText, setInputText] = useState('')
  const controllerRef = useRef(null)
  const areaRef = useRef(null)
  const gutterRef = useRef(null)
  const outRef = useRef(null)
  const startRef = useRef(0)

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
    onOutputChange && onOutputChange({ lines, exitCode })
  }, [lines, exitCode])

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

  function run() {
    if (running) {
      controllerRef.current?.abort()
      setRunning(false)
      return
    }
    setLines([])
    setExitCode(null)
    setRunId(null)
    setInputText('')
    setRunning(true)
    const controller = new AbortController()
    controllerRef.current = controller
    api.streamRun(
      { code, language: 'python' },
      {
        onRun: (id) => setRunId(id),
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

  function copyOutput() {
    const text = lines.map((l) => l.text).join('\n')
    if (!text) return
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(() => fallbackCopy(text))
    } else {
      fallbackCopy(text)
    }
  }

  function fallbackCopy(text) {
    const el = document.createElement('textarea')
    el.value = text
    el.style.position = 'fixed'
    el.style.opacity = '0'
    document.body.appendChild(el)
    el.select()
    try {
      document.execCommand('copy')
    } catch {}
    document.body.removeChild(el)
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
    ? `// running… ${elapsed}s`
    : exitCode === null
      ? '// ready'
      : exitCode === -1
        ? '// killed'
        : `// exit ${exitCode}`

  return (
    <aside className="ide-pane" style={{ width }}>
      <div className="ide-head">
        <span className="hash">#</span>
        <span className="ide-title">ide</span>
        <span style={{ flex: 1 }} />
        <button className="term-btn" onClick={copyOutput}>
          copy
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
      <pre className="ide-out" ref={outRef}>
        {lines.map((l, i) => (
          <div key={i} className={`ide-line${l.stream === 'stderr' ? ' err' : ''}${l.stream === 'stdin' ? ' in' : ''}`}>
            {l.text}
          </div>
        ))}
      </pre>
      {running && (
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
