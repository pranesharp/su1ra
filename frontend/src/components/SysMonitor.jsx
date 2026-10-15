import { useEffect, useState } from 'react'

// btop-lite: segmented utilization meters in the bottom-left corner.
// Each meter is a row of SEGS small blocks between [ ] brackets; lit blocks
// take the component color (G gpu = accent, M ram = h-b, D disk = h-c,
// C cpu = h-d — the accent-derived hue family), unlit blocks stay as faint ghosts so "0%" still reads as a
// live meter. No numbers on screen — hover for the actual percentage.
//
// Layout (two bottom-aligned columns):
//     one gpu                   two gpus
//                               M  [....]
//     M  [....]   D [....]      G1 [....]   D [....]   <- extra GPUs stack
//     G0 [....]   C [....]      G0 [....]   C [....]      upward on top of G0
// G0 is always the lowest row = gpu 0 = the integrated GPU (backend sorts
// iGPU first). With no measurable GPU a single dimmed G row stays.
//
// States: live (blocks) · unavailable (no source → flat line, glyph dimmed)
// · offline (backend not answering /api/sysmon → whole cluster dimmed).

const SEGS = 10

const RAM = { key: 'ram', glyph: 'M', name: 'memory', color: 'var(--h-b)' }
const DISK = { key: 'disk', glyph: 'D', name: 'disk', color: 'var(--h-c)' }
const CPU = { key: 'cpu', glyph: 'C', name: 'cpu', color: 'var(--h-d)' }

function Meter({ glyph, sub, color, value, title }) {
  const na = value === null || value === undefined
  const v = na ? 0 : Math.max(0, Math.min(100, value))
  // any nonzero load lights at least one block
  const lit = na ? 0 : v > 0 ? Math.max(1, Math.round((v / 100) * SEGS)) : 0
  return (
    <span className={`sysmon-cell${na ? ' na' : ''}`} title={title} style={{ '--sm-c': color }}>
      <span className="sysmon-glyph">
        {glyph}
        {sub !== undefined && <sub>{sub}</sub>}
      </span>
      <span className="sysmon-track">
        {Array.from({ length: SEGS }, (_, i) => (
          <span key={i} className={`sysmon-seg${i < lit ? ' on' : ''}`} />
        ))}
      </span>
    </span>
  )
}

function statTitle(b, v, offline) {
  if (offline) return `${b.name}: offline`
  if (v === null || v === undefined) return `${b.name}: unavailable`
  return `${b.name} ${Math.round(v)}%`
}

function gpuTitle(g, i, offline) {
  if (offline) return `gpu ${i}: offline`
  const head = `gpu ${i} · ${g.name}${g.integrated ? ' (integrated)' : ''}`
  if (g.util === null || g.util === undefined) return `${head} · usage unavailable`
  const mem = g.mem_gb !== null && g.mem_gb !== undefined ? ` · ${g.mem_gb} GB gpu memory` : ''
  return `${head} · ${Math.round(g.util)}%${mem}`
}

export default function SysMonitor() {
  const [stats, setStats] = useState(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let alive = true
    let misses = 0
    async function poll() {
      try {
        const res = await fetch('/api/sysmon')
        if (!res.ok) throw new Error(String(res.status))
        const data = await res.json()
        if (!alive) return
        misses = 0
        setOffline(false)
        setStats(data)
      } catch {
        /* backend pre-dates /api/sysmon or unreachable — keep last known bars */
        if (!alive) return
        misses += 1
        if (misses >= 3) setOffline(true)
      }
    }
    poll()
    const id = setInterval(poll, 2000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  const val = (k) => (offline ? null : (stats?.[k] ?? null))
  const gpus = Array.isArray(stats?.gpus) ? stats.gpus : []

  // top-to-bottom render order: highest index first, gpu 0 last (lowest row)
  const gpuRows = gpus.length
    ? gpus
        .map((g, i) => (
          <Meter
            key={`gpu${i}`}
            glyph="G"
            sub={i}
            color="var(--accent)"
            value={offline ? null : g.util}
            title={gpuTitle(g, i, offline)}
          />
        ))
        .reverse()
    : [
        <Meter
          key="gpu-none"
          glyph="G"
          color="var(--accent)"
          value={null}
          title={offline ? 'gpu: offline' : 'gpu: no measurable gpu found'}
        />,
      ]

  const stat = (b) => (
    <Meter key={b.key} glyph={b.glyph} color={b.color} value={val(b.key)} title={statTitle(b, val(b.key), offline)} />
  )

  return (
    <div
      className={`sysmon${offline ? ' off' : ''}`}
      aria-label="system monitor"
      title={offline ? 'sysmon offline — restart the app so the backend picks it up' : undefined}
    >
      <div className="sysmon-col">
        {stat(RAM)}
        {gpuRows}
      </div>
      <div className="sysmon-col">
        {stat(DISK)}
        {stat(CPU)}
      </div>
    </div>
  )
}
