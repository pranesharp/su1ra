async function handle(res) {
  if (res.ok) return res.json()
  let detail = res.statusText
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') detail = body.detail
    else if (body.detail) detail = JSON.stringify(body.detail)
  } catch {}
  const err = new Error(detail)
  err.status = res.status
  throw err
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

export const cancelPull = (model) => sendJSON('/api/models/pull/cancel', 'POST', { model })

export const deleteMessageFrom = (id) => sendJSON(`/api/messages/${id}/following`, 'DELETE')

export async function pullModel(model, onEvent, signal) {
  const resp = await fetch('/api/models/pull', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
    signal,
  })
  if (!resp.ok) {
    const err = new Error(`pull failed (${resp.status})`)
    await resp.body?.cancel()
    throw err
  }
  const reader = resp.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let nl
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (line) onEvent(JSON.parse(line))
    }
  }
}

export const getSettings = () => getJSON('/api/settings')

export const getConversations = () => getJSON('/api/conversations')

export const getConversation = (id) => getJSON(`/api/conversations/${id}`)

export const createConversation = (data = {}) => sendJSON('/api/conversations', 'POST', data)

export const updateConversation = (id, patch) => sendJSON(`/api/conversations/${id}`, 'PATCH', patch)

export const deleteConversation = (id) => sendJSON(`/api/conversations/${id}`, 'DELETE')

export const clearAllConversations = () => sendJSON('/api/conversations/clear-all', 'POST')

export const clearConversation = (id) => sendJSON(`/api/conversations/${id}/clear`, 'POST')

export const saveSettings = (data) => sendJSON('/api/settings', 'PATCH', data)
export const getBundledPrompt = () => getJSON('/api/system-prompt/bundled')
export const getPromptFile = () => getJSON('/api/system-prompt/file')
export const openPromptInEditor = (content) => sendJSON('/api/system-prompt/open', 'POST', { content })
export const downloadArtifact = (content, filename, extra) => sendJSON('/api/download', 'POST', { content, filename, ...(extra || {}) })
export const previewFile = (path) => sendJSON('/api/preview', 'POST', { path })

export const deleteModel = (name) => sendJSON(`/api/models/${encodeURIComponent(name)}`, 'DELETE')

export const unloadModel = (model) => sendJSON('/api/models/unload', 'POST', { model })

export const ejectServer = () => sendJSON('/api/eject', 'POST')

export const getGpu = () => getJSON('/api/gpu')

export const getModelCaps = (model) => getJSON(`/api/model/caps?model=${encodeURIComponent(model)}`)

export const attachmentUrl = (id) => `/api/attachments/${id}`

export async function uploadAttachment(conversationId, file) {
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('could not read file'))
    reader.readAsDataURL(file)
  })
  const comma = dataUrl.indexOf(',')
  const base64 = dataUrl.slice(comma + 1)
  const body = await sendJSON('/api/attachments', 'POST', {
    conversation_id: conversationId,
    filename: file.name || '',
    mime: file.type || '',
    data: base64,
  })
  return body.attachment
}

// Wayland/Hyprland drops arrive as text/uri-list, so the webview cannot read
// the file — send the path and let the backend read it from disk.
export async function uploadAttachmentFromPath(conversationId, path, filename) {
  const body = await sendJSON('/api/attachments/from-path', 'POST', {
    conversation_id: conversationId,
    path,
    filename: filename || '',
  })
  return body.attachment
}

export const mkdirWorkspace = (path) => sendJSON('/api/workspace/mkdir', 'POST', { path })

export const readWorkspaceFile = (path) => getJSON(`/api/workspace/read?path=${encodeURIComponent(path)}`)

export const restartServer = () => sendJSON('/api/ollama/restart', 'POST', {})

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
      if (obj.user_id) handlers.onUserId?.(obj.user_id)
      if (obj.tool_start) handlers.onToolStart?.(obj.tool_start)
      if (obj.tool) handlers.onTool?.(obj.tool)
      if (obj.stats) handlers.onStats?.(obj.stats)
      if (obj.done) {
        handlers.onDone?.(obj)
        return
      }
    }
  }
  handlers.onDone?.()
}

export async function streamRun(body, handlers, signal) {
  const res = await fetch('/api/run', {
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
      if (obj.run) {
        handlers.onRun(obj.run, obj.term === true)
        continue
      }
      if (obj.o) {
        handlers.onTerm?.(obj.o)
        continue
      }
      if (obj.error) {
        handlers.onError(obj.error)
        return
      }
      if (obj.stream) handlers.onLine(obj.stream, obj.line)
      if (obj.exit !== undefined) {
        handlers.onExit(obj.exit)
        return
      }
    }
  }
  handlers.onExit(null)
}

export async function sendRunInput(runId, text) {
  const res = await fetch('/api/run/input', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: runId, text }),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const errBody = await res.json()
      if (typeof errBody.detail === 'string') detail = errBody.detail
    } catch {}
    throw new Error(detail)
  }
  return res.json()
}

export async function pageInfo(url) {
  const res = await fetch('/api/page/info', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) throw new Error(res.statusText)
  return res.json()
}

export async function pageSummarize(conversationId, url) {
  const res = await fetch('/api/page/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, url }),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const errBody = await res.json()
      if (typeof errBody.detail === 'string') detail = errBody.detail
    } catch {}
    throw new Error(detail)
  }
  return res.json()
}
