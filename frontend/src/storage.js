const memory = new Map()

export function storageGet(key) {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return memory.has(key) ? memory.get(key) : null
  }
}

export function storageSet(key, value) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    memory.set(key, value)
  }
}
