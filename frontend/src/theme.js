export const DEFAULT_ACCENT = '#bf264a'

// Stamped into index.html by the backend (serve_index) from the DB, so the
// very first paint already uses the saved theme instead of these defaults.
export function readInjectedTheme() {
  try {
    const t = window?.__SU1RA_THEME__
    if (!t || typeof t !== 'object') return {}
    const out = {}
    if (typeof t.accent === 'string' && /^#[0-9a-fA-F]{6}$/.test(t.accent)) out.accent = t.accent
    if (Number.isFinite(+t.bg_brightness)) out.bgBrightness = Math.max(0, Math.min(150, +t.bg_brightness))
    if (Number.isFinite(+t.bg_contrast)) out.bgContrast = Math.max(0, Math.min(150, +t.bg_contrast))
    return out
  } catch {
    return {}
  }
}

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

function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('')
}

// btop-style panel hues: an ANALOGOUS family derived from the accent, so
// every theme gets in-family variation (crimson → raspberry/teal; amber →
// gold/green) instead of random colors. --h-a IS the accent; b/c/d rotate
// the hue (and calm the saturation a touch) for panel borders/titles/bars.
export function deriveHueFamily(hex) {
  const [r, g, b] = hexToRgb(hex).map((v) => v / 255)
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  const d = max - min
  let h = 0
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1))
  if (d !== 0) {
    if (max === r) h = 60 * (((g - b) / d) % 6)
    else if (max === g) h = 60 * ((b - r) / d + 2)
    else h = 60 * ((r - g) / d + 4)
  }
  if (h < 0) h += 360
  const wrap = (x) => (x % 360 + 360) % 360
  const mk = (hue, satF = 1, lightF = 1) => {
    const s2 = Math.min(0.85, s * satF)
    const l2 = Math.max(0.2, Math.min(0.72, l * lightF + 0.12))
    const c = (1 - Math.abs(2 * l2 - 1)) * s2
    const x = c * (1 - Math.abs(((hue / 60) % 2) - 1))
    const m = l2 - c / 2
    const seg = Math.floor(hue / 60) % 6
    const [r1, g1, b1] = [
      [c, x, 0],
      [x, c, 0],
      [0, c, x],
      [0, x, c],
      [x, 0, c],
      [c, 0, x],
    ][seg]
    return rgbToHex((r1 + m) * 255, (g1 + m) * 255, (b1 + m) * 255)
  }
  return {
    a: hex, // the accent itself
    b: mk(wrap(h + 45), 0.8), // analogous clockwise
    c: mk(wrap(h - 50), 0.75), // analogous counter-clockwise
    d: mk(wrap(h + 105), 0.6), // a third relative, calmer
  }
}

export function applyAccent(hex) {
  const root = document.documentElement.style
  hex = hex || DEFAULT_ACCENT // defense in depth — an undefined accent must not crash the render
  root.setProperty('--accent', hex)
  root.setProperty('--accent-bright', mix(hex, '#ffffff', 0.3))
  root.setProperty('--accent-soft', alpha(hex, 0.12))
  root.setProperty('--accent-text', mix(hex, '#000000', 0.82))
  root.setProperty('--user-bubble', alpha(hex, 0.16))
  // btop panel family — rotates with every accent pick
  const fam = deriveHueFamily(hex)
  root.setProperty('--h-a', fam.a)
  root.setProperty('--h-b', fam.b)
  root.setProperty('--h-c', fam.c)
  root.setProperty('--h-d', fam.d)
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
