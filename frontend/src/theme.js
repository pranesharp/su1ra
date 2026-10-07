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

export const DEFAULT_BRIGHTNESS = 100
export const DEFAULT_CONTRAST = 100

// Dark surfaces dimmed by brightness/contrast. Matches the :root palette.
const BASE_BG = {
  '--bg': '#0b0b0e',
  '--panel': '#08080a',
  '--surface': '#121216',
  '--surface-2': '#1a1a20',
  '--code-bg': '#0e0e12',
}

// Mean channel values of the palette above — the contrast pivot.
const PIVOT = [15, 15, 19]

function clamp8(v) {
  return Math.max(0, Math.min(255, Math.round(v)))
}

export function adjustBg(hex, brightness, contrast) {
  const m = brightness / 100
  const f = contrast / 100
  const c = hexToRgb(hex).map((v, i) => {
    const lit = v * m
    return clamp8(PIVOT[i] + (lit - PIVOT[i]) * f)
  })
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
}

// Past this brightness the dark palette washes out, so crossfade to a
// warm paper light-theme instead (fully light at LIGHT_FULL).
const LIGHT_START = 115
const LIGHT_FULL = 140

const LIGHT_FG = {
  '--bg': '#f0ede4',
  '--panel': '#faf8f1',
  '--surface': '#e7e1d2',
  '--surface-2': '#d9d2bd',
  '--code-bg': '#e3ddcc',
  '--border': '#c9c1ab',
  '--text': '#282420',
  '--muted': '#6e6759',
  '--faint': '#a39c87',
}

const DARK_FG = {
  '--border': '#26262c',
  '--text': '#d6d6d6',
  '--muted': '#8b8b92',
  '--faint': '#6b6b72',
}

function mixRgb(a, b, t) {
  return a.map((v, i) => Math.round(v * (1 - t) + b[i] * t))
}

function rgbStr(c) {
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
}

function parseRgb(str) {
  const m = String(str).match(/\d+/g) || []
  return [Number(m[0] || 0), Number(m[1] || 0), Number(m[2] || 0)]
}

export function lightBlend(brightness) {
  return Math.max(0, Math.min(1, (brightness - LIGHT_START) / (LIGHT_FULL - LIGHT_START)))
}

export function applyBackground(brightness = DEFAULT_BRIGHTNESS, contrast = DEFAULT_CONTRAST) {
  const root = document.documentElement.style
  const t = lightBlend(brightness)
  for (const [name, hex] of Object.entries(BASE_BG)) {
    const dark = parseRgb(adjustBg(hex, brightness, contrast))
    const c = t > 0 ? mixRgb(dark, hexToRgb(LIGHT_FG[name]), t) : dark
    root.setProperty(name, rgbStr(c))
  }
  // foreground follows the same crossfade so text stays readable on paper
  for (const [name, hex] of Object.entries(DARK_FG)) {
    const dark = hexToRgb(hex)
    const c = t > 0 ? mixRgb(dark, hexToRgb(LIGHT_FG[name]), t) : dark
    root.setProperty(name, rgbStr(c))
  }
  document.documentElement.dataset.mode = t >= 0.5 ? 'light' : 'dark'
}
