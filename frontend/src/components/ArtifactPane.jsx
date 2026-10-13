import { useEffect, useState } from 'react'
import { pageInfo, pageSummarize } from '../api'

export default function ArtifactPane({ width, code, tab, onTab, onClose, onDownload, path, browserUrl, browserHistory, browserIndex, browserEngine, onBrowserNavigate, onBrowserBack, onBrowserForward, onBrowserClose, onBrowserEngineChange, conversationId, onSummarize }) {
  const [urlText, setUrlText] = useState(browserUrl || '')
  const [info, setInfo] = useState(null)
  const [summarizing, setSummarizing] = useState(false)
  useEffect(() => {
    setUrlText(browserUrl || '')
  }, [browserUrl])

  // Probe the page: frameable? fetchable html? Drives the badge and the
  // blocked/summarize affordances. Never blocks the iframe from loading.
  useEffect(() => {
    if (!browserUrl) { setInfo(null); return }
    let alive = true
    setInfo(null)
    pageInfo(browserUrl)
      .then((d) => { if (alive) setInfo(d) })
      .catch(() => { if (alive) setInfo(null) })
    return () => { alive = false }
  }, [browserUrl])

  async function summarize() {
    if (!browserUrl || summarizing) return
    setSummarizing(true)
    try {
      const page = await pageSummarize(conversationId, browserUrl)
      onSummarize(page)
    } catch (err) {
      onSummarize({ error: err.message, url: browserUrl })
    } finally {
      setSummarizing(false)
    }
  }

  if (browserUrl) {
    const blocked = info && info.frameable === false
    const isHtml = info && info.kind === 'html'
    const isJs = info && info.kind === 'js'
    return (
      <aside className="ide-pane" style={{ width }}>
        <div className="browser-bar">
          <button className="term-btn" disabled={browserIndex <= 0} onClick={onBrowserBack}>
            ←
          </button>
          <button className="term-btn" disabled={browserIndex >= browserHistory.length - 1} onClick={onBrowserForward}>
            →
          </button>
          <button className="term-btn" onClick={() => onBrowserNavigate(browserUrl)}>
            ⟳
          </button>
          <select className="browser-engine" value={browserEngine} onChange={(e) => onBrowserEngineChange(e.target.value)}>
            <option value="google">Google</option>
            <option value="brave">Brave</option>
            <option value="ddg">DuckDuckGo</option>
            <option value="yandex">Yandex</option>
            <option value="bing">Bing</option>
          </select>
          <input
            type="text"
            className="browser-url"
            value={urlText}
            spellCheck={false}
            placeholder="type a URL or search query"
            onChange={(e) => setUrlText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') onBrowserNavigate(urlText) }}
          />
          {info && (
            <span className={`browser-badge ${isHtml ? 'ok' : 'warn'}`} title={info.frame_reason || ''}>
              {isHtml ? '✓ html' : isJs ? '✗ js' : blocked ? '✗ blocked' : '?'}
            </span>
          )}
          <button className="term-btn" onClick={() => window.open(browserUrl, '_blank')}>
            open externally
          </button>
          <button className="term-btn" onClick={onBrowserClose}>
            close
          </button>
        </div>
        {blocked ? (
          <div className="browser-blocked">
            <p>// this site blocks embedding (X-Frame-Options)</p>
            <button className="term-btn accent" onClick={() => window.open(browserUrl, '_blank')}>
              [ open externally ]
            </button>
          </div>
        ) : (
          <iframe className="browser-frame" src={browserUrl} sandbox="allow-scripts allow-same-origin allow-forms allow-popups" title="browser" />
        )}
        <div className="browser-foot">
          {isHtml ? (
            <button className="term-btn accent" disabled={summarizing} onClick={summarize}>
              {summarizing ? '[ summarizing… ]' : '[ summarize page ]'}
            </button>
          ) : (
            <span className="browser-note">
              {isJs
                ? '// JavaScript-rendered page — content not in the HTML, cannot summarize'
                : blocked
                  ? '// blocked from embedding — use [ open externally ]'
                  : '// checking page…'}
            </span>
          )}
        </div>
      </aside>
    )
  }

  return (
    <aside className="ide-pane" style={{ width }}>
      <div className="ide-head">
        <span className="hash">#</span>
        <span className="ide-title">{path ? path : 'artifact'}</span>
        <span style={{ flex: 1 }} />
        <button className={'term-btn' + (tab === 'preview' ? ' on' : '')} onClick={() => onTab('preview')}>
          preview
        </button>
        <button className={'term-btn' + (tab === 'code' ? ' on' : '')} onClick={() => onTab('code')}>
          code
        </button>
        <button className="term-btn" onClick={onDownload}>
          download
        </button>
        <button className="term-btn" onClick={onClose}>
          close
        </button>
      </div>
      {tab === 'preview' ? (
        <iframe className="artifact-frame" sandbox="allow-scripts" srcDoc={code} title="artifact preview" />
      ) : (
        <pre className="artifact-code">{code}</pre>
      )}
      <div className="ide-status">// sandboxed preview — scripts run isolated from the app</div>
    </aside>
  )
}
