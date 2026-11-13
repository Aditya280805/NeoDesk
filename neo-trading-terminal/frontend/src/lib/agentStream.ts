import { apiBase, ApiError } from './api'

// Only completed events may become final answers. Deltas remain untrusted JSON.
export async function agentStream(path: string, body: unknown, signal: AbortSignal,
  onStage: (stage: string) => void): Promise<unknown> {
  const response = await fetch(`${apiBase()}/api${path}/stream`, {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-NeoDesk': '1' },
    body: JSON.stringify(body), signal: AbortSignal.any([signal, AbortSignal.timeout(120000)]),
  })
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('neodesk:session-expired'))
    const data = await response.json().catch(() => ({}))
    throw new ApiError(typeof data.detail === 'string' ? data.detail : data.detail?.message || `Request failed (${response.status})`,
      response.status, data.detail?.code || response.headers.get('X-Options-Error-Code') || undefined,
      response.headers.get('X-Options-Run-Id') || undefined)
  }
  if (!response.body) throw new Error('The server returned no response stream.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      buffer = buffer.replace(/\r\n/g, '\n')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const lines = frame.split('\n')
        const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim()
        const raw = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
        if (!raw) continue
        const data = JSON.parse(raw)
        if (event === 'stage') onStage(data.stage)
        if (event === 'error') throw new ApiError(data.detail || 'Agent failed.', data.status_code || 503, data.code, data.run_id)
        if (event === 'completed') return data
      }
      if (buffer.length > 1048576) throw new Error('Response stream exceeded its size limit.')
      if (done) throw new Error('Connection ended before the answer was validated. Please retry.')
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
