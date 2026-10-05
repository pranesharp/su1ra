import { useEffect, useRef, useState } from 'react'
import { pullModel, cancelPull, deleteModel } from '../api'

const FAMILIES = [
  {
    fam: 'qwen3.5',
    blurb: 'qwen flagship — vision, thinking, 200+ languages',
    vars: [
      ['0.8b', '1.0 GB'], ['2b', '2.7 GB'], ['4b', '3.4 GB'],
      ['9b', '6.6 GB'], ['27b', '17 GB'], ['35b-a3b', '24 GB'],
    ],
  },
  {
    fam: 'gemma4',
    blurb: 'google — vision + thinking; e-series built for laptops',
    vars: [
      ['e2b', '4.6 GB'], ['e4b', '6.6 GB'], ['12b', '8.0 GB'],
      ['26b-a4b', '18 GB'], ['31b', '20 GB'],
    ],
  },
  {
    fam: 'gpt-oss',
    blurb: 'openai open-weight — native tools + thinking',
    vars: [['20b', '14 GB'], ['120b', '65 GB']],
  },
  {
    fam: 'qwen3-coder',
    blurb: 'agentic coder — 256k ctx, repo-scale tasks',
    vars: [['30b', '19 GB'], ['480b', '290 GB']],
  },
  {
    fam: 'qwen3.8',
    blurb: 'newest qwen generation',
    vars: [['27b', '18 GB']],
  },
  {
    fam: 'deepseek-r1',
    blurb: 'reasoning specialist — thinking blocks',
    vars: [
      ['1.5b', '1.1 GB'], ['7b', '4.7 GB'], ['8b', '5.2 GB'],
      ['14b', '9.0 GB'], ['32b', '20 GB'], ['70b', '43 GB'],
    ],
  },
  {
    fam: 'qwen2.5-coder',
    blurb: 'coder workhorse — still excellent at small sizes',
    vars: [
      ['1.5b', '1.0 GB'], ['3b', '1.9 GB'], ['7b', '4.7 GB'],
      ['14b', '9.0 GB'], ['32b', '20 GB'],
    ],
  },
  {
    fam: 'maternion/mimo-v2.6',
    blurb: 'xiaomi agentic coder — community upload',
    vars: [['9b', '5.6 GB'], ['9b-instruct', '5.6 GB']],
  },
  {
    fam: 'deepseek-coder',
    blurb: 'legacy coder (2024) — superseded by qwen3-coder',
    vars: [['1.3b', '0.8 GB'], ['6.7b', '3.8 GB'], ['33b', '19 GB']],
  },
]

const SINGLES = [
  ['ornith-1.5:9b', '9B · 6.6 GB · tools, thinking, vision', 'your current daily driver'],
  ['llama3.2:3b', '3B · 2.0 GB · tools', 'compact meta model'],
  ['phi4-mini:3.8b', '3.8B · 2.5 GB', 'reasoning + math leader at small size'],
  ['mistral:7b', '7.2B · 4.4 GB', 'fast, efficient all-rounder'],
]

export default function ModelHub({ models, onModelsChanged, onClose }) {
  const [pullName, setPullName] = useState('')
  const [pull, setPull] = useState(null)
  const [confirmRm, setConfirmRm] = useState(null)
  const [rmBusy, setRmBusy] = useState(null)
  const [rmErr, setRmErr] = useState('')
  const confirmTimer = useRef(null)
  const [openFams, setOpenFams] = useState(() => new Set())
  const [disk, setDisk] = useState(0)
  const pullCtrl = useRef(null)

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    fetch('/api/disk')
      .then((r) => r.json())
      .then((d) => setDisk(d.free || 0))
      .catch(() => {})
    return () => {
      window.removeEventListener('keydown', onKey)
      if (confirmTimer.current) clearTimeout(confirmTimer.current)
    }
  }, [onClose])

  const installed = new Set(models.map((m) => m.name))
  const pullActive = pull && !pull.done && !pull.err

  async function startPull(name) {
    name = (name || '').trim()
    if (!name || pullActive) return
    const ctrl = new AbortController()
    pullCtrl.current = ctrl
    setPull({ name, pct: null, status: 'starting', done: false, err: '' })
    try {
      await pullModel(
        name,
        (evt) => {
          if (evt.error) setPull((p) => (p ? { ...p, err: evt.error } : p))
          else if (evt.status === 'success') setPull((p) => (p ? { ...p, done: true, pct: 100, status: 'done' } : p))
          else if (evt.pct !== undefined) setPull((p) => (p ? { ...p, pct: evt.pct, status: 'pulling' } : p))
          else setPull((p) => (p ? { ...p, status: evt.status } : p))
        },
        ctrl.signal,
      )
      setPull((p) => (p && !p.err ? { ...p, done: true, pct: 100, status: 'done' } : p))
      onModelsChanged?.()
    } catch (err) {
      if (!ctrl.signal.aborted) setPull((p) => (p ? { ...p, err: err.message } : p))
    } finally {
      pullCtrl.current = null
    }
  }

  function cancelActivePull() {
    if (pull?.name) cancelPull(pull.name)
    pullCtrl.current?.abort()
    setPull(null)
  }

  async function removeModel(tag) {
    if (rmBusy) return
    if (confirmRm !== tag) {
      setConfirmRm(tag)
      setRmErr('')
      if (confirmTimer.current) clearTimeout(confirmTimer.current)
      confirmTimer.current = setTimeout(() => setConfirmRm(null), 4000)
      return
    }
    if (confirmTimer.current) clearTimeout(confirmTimer.current)
    setConfirmRm(null)
    setRmBusy(tag)
    setRmErr('')
    try {
      await deleteModel(tag)
      onModelsChanged?.()
    } catch (err) {
      setRmErr(err.message)
    } finally {
      setRmBusy(null)
    }
  }

  function rmButton(tag) {
    return (
      <button
        className="btn-ghost"
        disabled={rmBusy !== null}
        onClick={() => removeModel(tag)}
      >
        {rmBusy === tag ? '[ … ]' : confirmRm === tag ? '[ sure? ]' : '[ rm ]'}
      </button>
    )
  }

  function toggleFam(fam) {
    setOpenFams((prev) => {
      const next = new Set(prev)
      if (next.has(fam)) next.delete(fam)
      else next.add(fam)
      return next
    })
  }

  function fmtPct(p) {
    return p === null || p === undefined ? '' : ` ${p}%`
  }

  function famInstalled(fam) {
    return fam.vars.filter((v) => installed.has(`${fam.fam}:${v[0]}`)).length
  }

  function variantRow(fullTag, label, size) {
    const isInstalled = installed.has(fullTag)
    const isPulling = pullActive && pull.name === fullTag
    return (
      <div key={fullTag} className={`hub-row hub-var${isPulling ? ' pulling' : ''}`}>
        <div className="hub-main">
          <span className="hub-name">{fullTag}</span>
          <span className="hub-specs">{size}</span>
        </div>
        {isPulling ? (
          <div className="pull-bar hub-bar">
            <div className="pull-fill" style={{ width: `${pull.pct ?? 0}%` }} />
          </div>
        ) : isInstalled ? (
          <span className="hub-actions">
            <span className="hub-specs">[ installed ]</span>
            {rmButton(fullTag)}
          </span>
        ) : (
          <button
            className="btn-ghost"
            disabled={pullActive && pull.name !== fullTag}
            onClick={() => { setPullName(fullTag); startPull(fullTag) }}
          >
            [ pull ]
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>model hub</h2>
        {disk > 0 && <p className="hub-disk">// {(disk / 1073741824).toFixed(1)} GB free where models are stored</p>}
        <div className="pull-section">
          <div className="pull-row">
            <input
              type="text"
              value={pullName}
              onChange={(e) => setPullName(e.target.value)}
              placeholder="any ollama model name, e.g. llama3.2:3b"
              disabled={pullActive}
              onKeyDown={(e) => e.key === 'Enter' && startPull(pullName)}
            />
            <button className="btn-accent" disabled={pullActive || !pullName.trim()} onClick={() => startPull(pullName)}>
              Pull
            </button>
          </div>
          {pull && (
            <div className="pull-progress">
              {pull.err ? (
                <span className="pull-err">// pull failed: {pull.err}</span>
              ) : pull.done ? (
                <span>// pulled {pull.name} — it is now in /models</span>
              ) : (
                <>
                  <div className="pull-bar">
                    <div className="pull-fill" style={{ width: `${pull.pct ?? 0}%` }} />
                  </div>
                  <span className="pull-pct">
                    pulling {pull.name} — {pull.status}…{fmtPct(pull.pct)}
                  </span>
                  <button className="btn-ghost" onClick={cancelActivePull}>cancel</button>
                </>
              )}
            </div>
          )}
        </div>
        {rmErr && <p className="pull-err">// delete failed: {rmErr}</p>}
        <div className="hub-list">
          {SINGLES.map(([tag, specs]) => (
            <div key={tag} className={`hub-row${pullActive && pull.name === tag ? ' pulling' : ''}`}>
              <div className="hub-main">
                <span className="hub-name">{tag}</span>
                <span className="hub-specs">{specs}</span>
              </div>
              {pullActive && pull.name === tag ? (
                <div className="pull-bar hub-bar">
                  <div className="pull-fill" style={{ width: `${pull.pct ?? 0}%` }} />
                </div>
              ) : installed.has(tag) ? (
                <span className="hub-actions">
                  <span className="hub-specs">[ installed ]</span>
                  {rmButton(tag)}
                </span>
              ) : (
                <button
                  className="btn-ghost"
                  disabled={pullActive}
                  onClick={() => { setPullName(tag); startPull(tag) }}
                >
                  [ pull ]
                </button>
              )}
            </div>
          ))}
          {FAMILIES.map((fam) => {
            const open = openFams.has(fam.fam)
            const count = famInstalled(fam)
            const isPullingFam = pullActive && pull.name.startsWith(`${fam.fam}:`)
            return (
              <div key={fam.fam} className="hub-fam">
                <div
                  className={`hub-row hub-famrow${isPullingFam ? ' pulling' : ''}`}
                  onClick={() => toggleFam(fam.fam)}
                >
                  <div className="hub-main">
                    <span className="hub-name">
                      <span className={`chev${open ? ' open' : ''}`}>▸</span> {fam.fam}
                      {count > 0 && <span className="hub-badge">{count} installed</span>}
                    </span>
                    <span className="hub-specs">{fam.blurb}</span>
                  </div>
                  <span className="hub-count">{fam.vars.length} variants</span>
                </div>
                {open && fam.vars.map(([v, size]) => variantRow(`${fam.fam}:${v}`, v, size))}
              </div>
            )
          })}
        </div>
        <p className="hub-hint">// catalog is curated — any model on ollama.com works by name above</p>
        <div className="modal-actions">
          <button className="btn-accent" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  )
}
