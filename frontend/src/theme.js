export const DEFAULT_ACCENT = '#bf264a'

export const ACCENTS = [
  { name: 'crimson', hex: '#bf264a' },
  { name: 'ember', hex: '#e05a26' },
  { name: 'amber', hex: '#d7a01f' },
  { name: 'lime', hex: '#a3e635' },
  { name: 'pine', hex: '#1db954' },
  { name: 'teal', hex: '#14b8a6' },
  { name: 'azure', hex: '#2f81f7' },
  { name: 'violet', hex: '#8b5cf6' },
  { name: 'magenta', hex: '#e0509f' },
  { name: 'silver', hex: '#94a3b8' },
]

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function mix(hex, target, p) {
  const a = hexToRgb(hex)
  const b = hexToRgb(target)
  const c = a.map((v, i) => Math.round(v * (1 - p) + b[i] * p))
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
}

function alpha(hex, p) {
  const [r, g, b] = hexToRgb(hex)
  return `rgba(${r}, ${g}, ${b}, ${p})`
}

export function applyAccent(hex) {
  const root = document.documentElement.style
  root.setProperty('--accent', hex)
  root.setProperty('--accent-bright', mix(hex, '#ffffff', 0.3))
  root.setProperty('--accent-soft', alpha(hex, 0.12))
  root.setProperty('--accent-text', mix(hex, '#000000', 0.82))
  root.setProperty('--user-bubble', alpha(hex, 0.16))
}
