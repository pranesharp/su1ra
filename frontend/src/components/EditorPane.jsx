import { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { EditorView, keymap } from '@codemirror/view'
import { EditorState, Compartment } from '@codemirror/state'
import { basicSetup } from 'codemirror'
import { python } from '@codemirror/lang-python'
import { javascript } from '@codemirror/lang-javascript'
import { html } from '@codemirror/lang-html'
import { css } from '@codemirror/lang-css'
import { json } from '@codemirror/lang-json'
import { markdown } from '@codemirror/lang-markdown'
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

// Editor pane: a scratch text editor (like a mini VS Code/kate).
//  - the buffer belongs to a FILENAME (relative path inside ~/Documents/.scratch)
//  - run executes the saved FILE with the interpreter matching the extension
//    (.py/.js/.sh/.ps1/.bat/.rb/.pl/.lua); html/svg render in the preview pane
//  - explorer sidebar: tree of the scratch folder, open/new-file/new-folder
//  - dirty tracking: "· unsaved" marker + ctrl+s saves
//  - CodeMirror 6 for highlighting/editing; xterm.js for PTY output
const RUNNABLE = new Set(['py', 'js', 'mjs', 'cjs', 'sh', 'bash', 'ps1', 'bat', 'cmd', 'rb', 'pl', 'lua'])
// Not terminal-runnable, but RENDERABLE: run opens the artifact preview pane.
const PREVIEWABLE = new Set(['html', 'htm', 'svg'])

function extOf(name) {
  return (name.split('.').pop() || '').toLowerCase()
}
function runnableName(name) {
  return RUNNABLE.has(extOf(name))
}
function previewableName(name) {
  return PREVIEWABLE.has(extOf(name))
}

// four box-drawing corner glyphs, positioned on the panel's border corners
function Corners() {
  return (
    <>
      <span className="btop-corner c-tl">┌</span>
      <span className="btop-corner c-tr">┐</span>
      <span className="btop-corner c-bl">└</span>
      <span className="btop-corner c-br">┘</span>
    </>
  )
}

function langFor(ext) {
  switch (ext) {
    case 'py':
      return python()
    case 'js':
    case 'mjs':
    case 'cjs':
      return javascript()
    case 'html':
    case 'htm':
    case 'svg':
      return html()
    case 'css':
      return css()
    case 'json':
      return json()
    case 'md':
    case 'markdown':
      return markdown()
    default:
      return null
  }
}

// Minimal CM themes that follow the app's light/dark data-mode, same colors
// the xterm theme flips between. Transparent background — sits on --surface.
function cmTheme(light) {
  return EditorView.theme(
    {
      '&': {
        color: light ? '#2b2620' : '#c6c6cc',
        backgroundColor: 'transparent',
        fontSize: '13px',
      },
      '.cm-content': { fontFamily: 'var(--mono), monospace', caretColor: 'var(--accent)' },
      '&.cm-focused': { outline: 'none' },
      '.cm-gutters': {
        backgroundColor: 'transparent',
        color: light ? '#8a8378' : '#4a4a55',
        border: 'none',
        fontFamily: 'var(--mono), monospace',
        fontSize: '11.5px',
      },
      '.cm-activeLineGutter': { backgroundColor: light ? '#0000000d' : '#ffffff0a' },
      '.cm-activeLine': { backgroundColor: light ? '#00000006' : '#ffffff06' },
      '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': {
        backgroundColor: light ? '#b9b09a55' : '#3a3a4166',
      },
      '.cm-cursor': { borderLeftColor: 'var(--accent)' },
    },
    { dark: !light },
  )
}

export default function EditorPane({ width, code, filename, onCodeChange, onFilenameChange, onClose, onResizeStart, onOutputChange, onSendToChat, onPreview, runSignal }) {
  const [lines, setLines] = useState([])
  const [running, setRunning] = useState(false)
  const [exitCode, setExitCode] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [runId, setRunId] = useState(null)
  const [inputText, setInputText] = useState('')
  const [termActive, setTermActive] = useState(false)
  const [plainOut, setPlainOut] = useState('')
  const [copyMark, setCopyMark] = useState(null)
  const [saveMark, setSaveMark] = useState(null)
  // dirty tracking: buffer vs last-saved snapshot (synced on save + programmatic loads)
  const [snapshot, setSnapshot] = useState(code)
  // explorer state
  const [explorerOpen, setExplorerOpen] = useState(true)
  const [tree, setTree] = useState(null)
  const [expanded, setExpanded] = useState(() => new Set())
  // two-click delete confirm (window.confirm is unreliable in webview shells)
  const [confirmDel, setConfirmDel] = useState(null)
  const controllerRef = useRef(null)
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
  // CodeMirror
  const cmHostRef = useRef(null)
  const cmRef = useRef(null)
  const langComp = useRef(new Compartment())
  const themeComp = useRef(new Compartment())
  const codeRef = useRef(code)
  const saveRef = useRef(() => {})
  // movable bottom section (output / terminal)
  const [termH, setTermH] = useState(240)
  const dragRef = useRef(null)
  const paneRef = useRef(null)

  const lineCount = code.split('\n').length
  const dirty = code !== snapshot

  useEffect(() => {
    codeRef.current = code
  }, [code])

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
  }, [width, explorerOpen, termH])

  // The terminal canvas keeps its own colors (transparent bg, so it sits on
  // --surface): follow the html data-mode that applyBackground maintains and
  // flip the foreground when brightness crosses into light mode. Same for CM.
  useEffect(() => {
    function applyTermMode() {
      const term = termRef.current
      const light = document.documentElement.dataset.mode === 'light'
      if (term) {
        term.options.theme = {
          ...term.options.theme,
          foreground: light ? '#2b2620' : '#c6c6cc',
          cursorAccent: light ? '#f0ede4' : '#101014',
          selectionBackground: light ? '#b9b09a66' : '#3a3a4166',
        }
      }
      try {
        themeComp.current.get(cmRef.current)?.length // noop guard
        cmRef.current?.dispatch({
          effects: themeComp.current.reconfigure(cmTheme(light)),
        })
      } catch {}
    }
    applyTermMode()
    const obs = new MutationObserver(applyTermMode)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-mode'] })
    return () => obs.disconnect()
  }, [])

  // swap the highlighting when the file's extension changes
  useEffect(() => {
    const view = cmRef.current
    if (!view) return
    view.dispatch({ effects: langComp.current.reconfigure(langFor(extOf(filename)) || []) })
  }, [filename])

  // external code changes (file open, load-to-editor): update CM + snapshot
  useEffect(() => {
    const view = cmRef.current
    if (!view) return
    if (view.state.doc.toString() === code) return
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: code } })
  }, [code])

  // --- explorer -------------------------------------------------------------
  async function refreshTree() {
    try {
      const t = await api.editorTree()
      setTree(t)
      return t
    } catch {
      return null
    }
  }

  useEffect(() => {
    refreshTree()
  }, [])

  async function openFile(rel) {
    try {
      const res = await api.editorOpen(rel)
      onFilenameChange(res.rel)
      onCodeChange(res.content)
      setSnapshot(res.content)
      setSaveMark(`opened ${res.rel}`)
      setTimeout(() => setSaveMark(null), 2000)
    } catch (err) {
      setSaveMark(`open failed: ${err.message}`)
      setTimeout(() => setSaveMark(null), 3500)
    }
  }

  function toggleDir(rel) {
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(rel) ? next.delete(rel) : next.add(rel)
      return next
    })
  }

  async function newFile() {
    // first non-colliding untitled name at the tree root
    const names = new Set((tree?.files || []).map((f) => f.name))
    let name = 'untitled.py'
    for (let i = 2; names.has(name); i++) name = `untitled-${i}.py`
    try {
      await api.editorMkdirFile({ filename: name, code: '' })
      const t = await refreshTree()
      setExpanded((prev) => new Set([...prev, '']))
      if (t) {
        const found = (t.files || []).find((f) => f.name === name)
        if (found) openFile(name)
      }
    } catch (err) {
      setSaveMark(`create failed: ${err.message}`)
      setTimeout(() => setSaveMark(null), 3500)
    }
  }

  async function newFolder() {
    const names = new Set((tree?.dirs || []).map((d) => d.name))
    let name = 'new-folder'
    for (let i = 2; names.has(name); i++) name = `new-folder-${i}`
    try {
      await api.editorMkdirFile({ filename: name, code: '' })
      await refreshTree()
      setExpanded((prev) => new Set([...prev, '']))
    } catch (err) {
      setSaveMark(`create failed: ${err.message}`)
      setTimeout(() => setSaveMark(null), 3500)
    }
  }

  async function deleteEntry(rel, isDir) {
    try {
      await api.editorDelete(rel)
      setConfirmDel(null)
      await refreshTree()
      // deleting the open file: drop the buffer back to a fresh scratch
      if (!isDir && rel === filename) {
        onFilenameChange('untitled.py')
        onCodeChange('')
        setSnapshot('')
        setSaveMark(`deleted ${rel}`)
        setTimeout(() => setSaveMark(null), 2500)
      }
    } catch (err) {
      setSaveMark(`delete failed: ${err.message}`)
      setConfirmDel(null)
      setTimeout(() => setSaveMark(null), 3500)
    }
  }

  function renderTree(node, relBase) {
    const rows = []
    for (const d of node.dirs || []) {
      const rel = relBase ? `${relBase}/${d.name}` : d.name
      const open = expanded.has(rel)
      rows.push(
        <div key={`d-${rel}`} className="explorer-row dir" onClick={() => toggleDir(rel)}>
          <span className="explorer-twist">{open ? '▾' : '▸'}</span>
          <span className="explorer-name">{d.name}/</span>
          <button
            className={`explorer-del${confirmDel === rel ? ' armed' : ''}`}
            title={confirmDel === rel ? `click again to delete ${rel}/` : `delete ${rel}/`}
            onClick={(e) => {
              e.stopPropagation()
              confirmDel === rel ? deleteEntry(rel, true) : setConfirmDel(rel)
            }}
          >
            {confirmDel === rel ? 'sure?' : '−'}
          </button>
        </div>,
      )
      if (open) {
        rows.push(
          <div key={`dc-${rel}`} className="explorer-children">
            {renderTree(d, rel)}
          </div>,
        )
      }
    }
    for (const f of node.files || []) {
      const rel = relBase ? `${relBase}/${f.name}` : f.name
      rows.push(
        <div
          key={`f-${rel}`}
          className={`explorer-row file${rel === filename ? ' active' : ''}`}
          onClick={() => openFile(rel)}
          title={`${f.name} · ${f.size} bytes`}
        >
          <span className="explorer-twist" />
          <span className="explorer-name">{f.name}</span>
          <button
            className={`explorer-del${confirmDel === rel ? ' armed' : ''}`}
            title={confirmDel === rel ? `click again to delete ${rel}` : `delete ${rel}`}
            onClick={(e) => {
              e.stopPropagation()
              confirmDel === rel ? deleteEntry(rel, false) : setConfirmDel(rel)
            }}
          >
            {confirmDel === rel ? 'sure?' : '−'}
          </button>
        </div>,
      )
    }
    return rows
  }

  // --- run machinery (unchanged semantics, filename now subpath-aware) ------
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
    // line numbers come from CodeMirror now — no custom gutter to sync
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
    // Previewable (html/svg): "run" means render — save, then hand the buffer
    // to the artifact pane. Nothing executes in a terminal.
    if (previewableName(filename)) {
      saveFile()
      onPreview && onPreview(codeRef.current, filename)
      return
    }
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
      { code: codeRef.current, filename },
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

  async function saveFile() {
    try {
      const res = await api.saveEditorFile({ code: codeRef.current, filename })
      setSnapshot(codeRef.current)
      setSaveMark(`saved → ${res.path}`)
      refreshTree()
      setTimeout(() => setSaveMark(null), 2500)
    } catch (err) {
      setSaveMark(`save failed: ${err.message}`)
      setTimeout(() => setSaveMark(null), 3500)
    }
  }

  saveRef.current = saveFile

  // ctrl+s anywhere while the pane is open
  useEffect(() => {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        saveRef.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  async function copyOutput() {
    const text = termActive ? plainOut : lines.map((l) => l.text).join('\n')
    if (!text) return
    const ok = await copyText(text)
    setCopyMark(ok ? 'copied' : 'failed')
    setTimeout(() => setCopyMark(null), 1500)
  }

  // --- bottom section drag (btop-style splitter) ---------------------------
  function startTermDrag(e) {
    if (e.button !== 0) return
    e.preventDefault()
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {}
    const pane = paneRef.current?.getBoundingClientRect()
    dragRef.current = {
      y: e.clientY,
      h: termH,
      max: pane ? Math.max(120, pane.height - 280) : 640,
    }
    document.body.classList.add('pane-resizing')
  }

  function moveTermDrag(e) {
    if (!dragRef.current) return
    const dy = dragRef.current.y - e.clientY // drag up = taller
    setTermH(Math.round(Math.max(90, Math.min(dragRef.current.max, dragRef.current.h + dy))))
  }

  function endTermDrag() {
    dragRef.current = null
    document.body.classList.remove('pane-resizing')
  }

  const canRun = runnableName(filename) || previewableName(filename)
  const runLabel = running ? 'stop' : previewableName(filename) ? 'preview' : 'run'
  const status = saveMark
    ? `// ${saveMark}`
    : running
      ? `// running ${filename}... ${elapsed}s`
      : exitCode === null
        ? dirty
          ? `// ${filename} · unsaved changes — ctrl+s to save`
          : runnableName(filename)
            ? `// ${filename} · ready`
            : previewableName(filename)
              ? `// ${filename} · preview ready`
              : `// ${filename} · not runnable — save only`
        : exitCode < 0
          ? `// killed`
          : `// exit ${exitCode}`

  // CodeMirror instance (once)
  useEffect(() => {
    if (!cmHostRef.current || cmRef.current) return
    const state = EditorState.create({
      doc: code,
      extensions: [
        basicSetup,
        langComp.current.of(langFor(extOf(filename)) || []),
        themeComp.current.of(cmTheme(document.documentElement.dataset.mode !== 'light')),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) onCodeChange(u.state.doc.toString())
        }),
        keymap.of([
          {
            key: 'Mod-s',
            preventDefault: true,
            run: () => {
              saveRef.current()
              return true
            },
          },
        ]),
      ],
    })
    const view = new EditorView({ state, parent: cmHostRef.current })
    cmRef.current = view
    return () => {
      view.destroy()
      cmRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <aside className="ide-pane" style={{ width }} ref={paneRef}>
      <div className="ide-head">
        <span className="hash">#</span>
        <span className="ide-title">editor</span>
        <button className={`term-btn${explorerOpen ? ' open' : ''}`} onClick={() => setExplorerOpen((v) => !v)} title="toggle the scratch file explorer">
          files
        </button>
        <input
          className="ide-filename"
          value={filename}
          onChange={(e) => onFilenameChange(e.target.value)}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          title="relative path inside ~/Documents/.scratch — the extension picks the interpreter"
        />
        {dirty && <span className="ide-dirty">· unsaved</span>}
        <span style={{ flex: 1 }} />
        <button className="term-btn" onClick={saveFile} title="ctrl+s">
          save
        </button>
        <button className="term-btn" onClick={copyOutput}>
          {copyMark === 'copied' ? 'copied' : copyMark === 'failed' ? 'copy failed' : 'copy'}
        </button>
        <button className="term-btn" onClick={onSendToChat}>
          send to chat
        </button>
        <button className="term-btn" onClick={run} disabled={!canRun} style={canRun ? {} : { opacity: 0.4, cursor: 'not-allowed' }} title={runnableName(filename) ? `run ${filename}` : previewableName(filename) ? `render ${filename} in the preview pane` : `${filename} — not runnable (save only)`}>
          {runLabel}
        </button>
        <button className="term-btn" onClick={onClose}>
          close
        </button>
      </div>
      <div className="ide-body">
        {explorerOpen && (
          <section className="panel h-b explorer-panel">
            <span className="panel-title">scratch</span>
            <Corners />
            <div className="explorer-head">
              <button className="btn-solid" onClick={newFile} title="new file">
                + file
              </button>
              <button className="btn-solid" onClick={newFolder} title="new folder">
                + dir
              </button>
            </div>
            <div className="explorer-tree">
              {tree ? (
                renderTree(tree, '')
              ) : (
                <div className="explorer-row file">
                  <span className="explorer-name">// loading…</span>
                </div>
              )}
            </div>
          </section>
        )}
        <section className="panel h-a code-panel">
          <span className="panel-title">editor</span>
          <Corners />
          <div className="cm-host" ref={cmHostRef} />
        </section>
      </div>
      <div className="ide-bottom panel h-c" style={{ height: termH }}>
        <div
          className="ide-split"
          onPointerDown={startTermDrag}
          onPointerMove={moveTermDrag}
          onPointerUp={endTermDrag}
          onPointerCancel={endTermDrag}
          title="drag to resize the output area"
        >
          <span className="split-label">output</span>
          <span className="split-grip">···</span>
        </div>
        <div className="ide-bottom-inner">
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
        </div>
        <Corners />
      </div>
      <div className="ide-status">{status}</div>
    </aside>
  )
}
