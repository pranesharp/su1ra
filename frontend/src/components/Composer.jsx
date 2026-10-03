import { useRef, useState } from 'react'

export default function Composer({ commands = [], disabled, streaming, onSend, onStop, codeArmed }) {
  const [text, setText] = useState('')
  const areaRef = useRef(null)

  const isCmdTyping = /^\/\w*$/.test(text)
  const suggestions = isCmdTyping ? commands.filter((c) => c.cmd.startsWith(text)) : []

  function resize() {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 208) + 'px'
  }

  function submit() {
    if (streaming) return
    const value = text.trim()
    if (!value) return
    onSend(value)
    setText('')
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
    }
  }

  return (
    <div className="composer-wrap">
      <div className={`composer${disabled && !text.startsWith('/') ? ' disabled' : ''}`}>
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
        />
        {streaming ? (
          <button className="term-btn stop" title="Stop generating" onClick={onStop}>
            [ stop ]
          </button>
        ) : (
          <button className="term-btn accent send" title="Send" disabled={!text.trim()} onClick={submit}>
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
      <div className="composer-hint">
        {codeArmed ? '// tools armed — run code enabled · ' : ''}
        enter to send · shift+enter for newline · /help for commands
      </div>
    </div>
  )
}
