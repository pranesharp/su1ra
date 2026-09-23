async function handle(res) {
  if (res.ok) return res.json()
  let detail = res.statusText
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') detail = body.detail
    else if (body.detail) detail = JSON.stringify(body.detail)
  } catch {}
  throw new Error(detail)
}

const getJSON = (path) => fetch(path).then(handle)

const sendJSON = (path, method, body) =>
  fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(handle)

export const getStatus = () => getJSON('/api/status')

export const getModels = () => getJSON('/api/models')

export const getConversations = () => getJSON('/api/conversations')

export const getConversation = (id) => getJSON(`/api/conversations/${id}`)

export const createConversation = (data = {}) => sendJSON('/api/conversations', 'POST', data)

export const updateConversation = (id, patch) => sendJSON(`/api/conversations/${id}`, 'PATCH', patch)

export const deleteConversation = (id) => sendJSON(`/api/conversations/${id}`, 'DELETE')

export const saveSettings = (data) => sendJSON('/api/settings', 'PATCH', data)

export const ejectServer = () => sendJSON('/api/eject', 'POST')

export const connectServer = () => sendJSON('/api/connect', 'POST', {})

export async function streamChat(body, handlers, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const errBody = await res.json()
      if (typeof errBody.detail === 'string') detail = errBody.detail
      else if (errBody.detail) detail = JSON.stringify(errBody.detail)
    } catch {}
    handlers.onError(detail)
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let newlineIndex
    while ((newlineIndex = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newlineIndex).trim()
      buffer = buffer.slice(newlineIndex + 1)
      if (!line) continue
      let obj
      try {
        obj = JSON.parse(line)
      } catch {
        continue
      }
      if (obj.error) {
        handlers.onError(obj.error)
        return
      }
      if (obj.delta) handlers.onDelta(obj.delta)
      if (obj.done) {
        handlers.onDone()
        return
      }
    }
  }
  handlers.onDone()
}
