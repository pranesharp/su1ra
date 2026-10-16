import { useEffect, useRef, useState } from 'react'
import { pageInfo, pageSummarize } from '../api'

export default function ArtifactPane({ width, code, tab, onTab, onClose, onDownload, path, browserUrl, browserHistory, browserIndex, browserEngine, onBrowserNavigate, onBrowserBack, onBrowserForward, onBrowserClose, onBrowserEngineChange, conversationId, onSummarize }) {
  const [urlText, setUrlText] = useState(browserUrl || '')
  const [info, setInfo] = useState(null)
  const [summarizing, setSummarizing] = useState(false)
  const [adblockOn, setAdblockOn] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const frameRef = useRef(null)
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

  // When adblock is on, the iframe loads through the backend rewrite proxy so
  // the blocklist <style> is injected into the fetched HTML.
  const frameSrc = adblockOn
    ? `/api/page/view?url=${encodeURIComponent(browserUrl)}`
    : browserUrl

  // Capture the current view (native screenshot when available) and hand it to
  // the chat as an image so a vision model can "see" the page.
  //
  // capture_pane() now returns IMMEDIATELY (it must not block the UI thread) and
  // delivers the PNG asynchronously by invoking window.__su1raCaptureResult(png).
  // So we register that callback, kick off the capture, and treat its arrival as
  // completion. If no result arrives within a few seconds we tell the user.
  async function capturePage() {
    if (!browserUrl || capturing) return
    if (!window.pywebview?.api?.capture_pane) {
      onSummarize({ error: 'screenshot requires the desktop app (no native bridge in browser preview)', url: 'capture' })
      return
    }
    setCapturing(true)
    const timer = setTimeout(() => {
      window.__su1raCaptureResult = null
      setCapturing(false)
      onSummarize({ error: 'screenshot timed out (no capture result)', url: 'capture' })
    }, 8000)
    window.__su1raCaptureResult = (pngBase64) => {
      clearTimeout(timer)
      window.__su1raCaptureResult = null
      setCapturing(false)
      onSummarize({ captured: pngBase64, url: browserUrl })
    }
    // Send the pane's on-screen rect so the native side can crop the window
    // shot down to just the page. CSS px viewport coords are the crop inputs
    // (the native side measures the real screen scale itself — dpr is ignored).
    let rect = null
    try {
      const el = frameRef.current
      if (el) {
        const r = el.getBoundingClientRect()
        rect = { x: r.left, y: r.top, w: r.width, h: r.height, dpr: window.devicePixelRatio || 1 }
      }
    } catch { /* crop is optional — full shot still works */ }
    try {
      await window.pywebview.api.capture_pane(rect) // returns '' immediately; result arrives via callback
    } catch (err) {
      clearTimeout(timer)
      window.__su1raCaptureResult = null
      setCapturing(false)
      onSummarize({ error: err?.message || String(err), url: 'capture' })
    }
    // (no finally: setCapturing(false) happens in the callback or the 8s timeout)
  }

  if (browserUrl) {
    const blocked = info && info.frameable === false
    const isHtml = info && info.kind === 'html'
    const isJs = info && info.kind === 'js'
    // Probe finished but inconclusive: the backend couldn't fetch/classify the
    // page (bot-protected origin, funneled through a blocked route, etc.). The
    // iframe may still render it fine — surface that state honestly instead of
    // implying the probe is still "checking".
    const inconclusive = info && !isHtml && !isJs && !blocked
    const probed = info && !blocked && (isHtml || isJs || inconclusive)
    const badgeTitle = info?.frame_reason
      ? `${info.frame_reason} — blocked from embedding`
      : inconclusive
        ? 'backend could not probe this page (blocked/unreachable) — iframe may still render it'
        : ''
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
            <span className={`browser-badge ${isHtml ? 'ok' : blocked || inconclusive ? 'warn' : 'warn'}`} title={badgeTitle}>
              {isHtml ? '✓ html' : isJs ? '✗ js' : blocked ? '✗ blocked' : inconclusive ? '✗ probe' : '?'}
            </span>
          )}
          <button
            className={`term-btn ${adblockOn ? 'accent' : ''}`}
            title="on: load through the backend rewrite proxy + blocklist (may fail on pages that block the backend)"
            onClick={() => setAdblockOn((v) => !v)}
          >
            ab: {adblockOn ? 'on' : 'off'}
          </button>
          <button
            className="term-btn"
            title="capture the current view and hand it to the chat as an image (vision model)"
            disabled={capturing}
            onClick={capturePage}
          >
            {capturing ? '[ snap... ]' : '[ capture ]'}
          </button>
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
          <iframe ref={frameRef} className="browser-frame" src={frameSrc} sandbox="allow-scripts allow-same-origin allow-forms allow-popups" title="browser" />
        )}
        <div className="browser-foot">
          {isHtml || inconclusive ? (
            <button className="term-btn accent" disabled={summarizing} onClick={summarize}>
              {summarizing ? '[ summarizing... ]' : '[ summarize page ]'}
            </button>
          ) : (
            <span className="browser-note">
              {isJs
                ? '// JavaScript-rendered page — content not in the HTML, cannot summarize'
                : blocked
                  ? '// blocked from embedding — use [ open externally ]'
                  : '// checking page...'}
            </span>
          )}
          {inconclusive && (
            <span className="browser-note browser-note-probe">
              // couldn't probe from the backend (blocked/unreachable) — iframe may still render it
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
