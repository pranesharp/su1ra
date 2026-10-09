import { useEffect, useState } from 'react'

function callApi(fn, ...args) {
  try {
    const api = window?.pywebview?.api
    if (api && typeof api[fn] === 'function') return api[fn](...args)
  } catch { /* browser dev — no native window */ }
  return Promise.resolve(null)
}

// Floating min/max/close — only renders when the backend exposes the
// window API over pywebview js_api (frameless mode). Otherwise the native
// OS frame owns the buttons and this returns null.
export default function WindowControls() {
  const [maxed, setMaxed] = useState(false)
  const hasApi = typeof window !== 'undefined'
    && typeof window.pywebview?.api?.minimize === 'function'

  useEffect(() => {
    let alive = true
    callApi('is_maximized').then((v) => { if (alive && typeof v === 'boolean') setMaxed(v) }).catch(() => {})
    const onResize = () => {
      callApi('is_maximized').then((v) => { if (alive && typeof v === 'boolean') setMaxed(v) }).catch(() => {})
    }
    window.addEventListener('resize', onResize)
    return () => { alive = false; window.removeEventListener('resize', onResize) }
  }, [])

  const min = () => callApi('minimize')
  const toggleMax = () => {
    setMaxed((m) => !m)
    callApi('toggle_maximize').catch(() => {})
    setTimeout(() => {
      callApi('is_maximized').then((v) => { if (typeof v === 'boolean') setMaxed(v) }).catch(() => {})
    }, 250)
  }
  const close = () => callApi('close')

  if (!hasApi) return null
  return (
    <span className="tb-controls">
      <button className="tb-btn" onClick={min} title="Minimize" aria-label="Minimize">
        <svg width="11" height="11" viewBox="0 0 11 11"><line x1="1" y1="5.5" x2="10" y2="5.5" stroke="currentColor" strokeWidth="1.2" /></svg>
      </button>
      <button className="tb-btn" onClick={toggleMax} title={maxed ? 'Restore' : 'Maximize'} aria-label={maxed ? 'Restore' : 'Maximize'}>
        {maxed ? (
          <svg width="11" height="11" viewBox="0 0 11 11"><rect x="2.5" y="1" width="7" height="7" fill="none" stroke="currentColor" strokeWidth="1.2" /><rect x="1" y="3" width="7" height="7" fill="var(--panel)" stroke="currentColor" strokeWidth="1.2" /></svg>
        ) : (
          <svg width="11" height="11" viewBox="0 0 11 11"><rect x="1.5" y="1.5" width="8" height="8" fill="none" stroke="currentColor" strokeWidth="1.2" /></svg>
        )}
      </button>
      <button className="tb-btn tb-close" onClick={close} title="Close" aria-label="Close">
        <svg width="11" height="11" viewBox="0 0 11 11"><line x1="1.5" y1="1.5" x2="9.5" y2="9.5" stroke="currentColor" strokeWidth="1.2" /><line x1="9.5" y1="1.5" x2="1.5" y2="9.5" stroke="currentColor" strokeWidth="1.2" /></svg>
      </button>
    </span>
  )
}
