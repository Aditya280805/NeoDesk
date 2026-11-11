const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

function load(file, dependencies, globals) {
  const module = { exports: {} }
  const source = fs.readFileSync(path.join(__dirname, '../src', file), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  vm.runInNewContext(compiled, { module, exports: module.exports,
    require: name => { if (!(name in dependencies)) throw new Error(name); return dependencies[name] }, ...globals })
  return module.exports
}

test('API preserves structured scope conflicts for callers', async () => {
  const { api } = load('lib/api.ts', {}, {
    process: { env: {} }, AbortSignal: { timeout: () => undefined },
    fetch: async () => ({ ok: false, status: 409, json: async () => ({
      detail: { code: 'conversation_scope_changed', message: 'Start a new chat.' },
    }) }),
  })
  await assert.rejects(api('/options-agent/chat'), error =>
    error.status === 409 && error.code === 'conversation_scope_changed' && error.message === 'Start a new chat.')
})

test('an old socket closing cannot disconnect the new signed-in session', () => {
  const sockets = [], states = []
  class Socket {
    static OPEN = 1
    static CONNECTING = 0
    readyState = 0
    constructor() { sockets.push(this) }
    close() {} // Browser onclose arrives asynchronously.
  }
  const { wsService } = load('services/ws.ts', {
    '@/lib/api': { apiBase: () => '' },
    '@/stores/marketStore': { useMarketStore: { getState: () => ({ setConnected: s => states.push(s) }) } },
  }, { window: { location: { protocol: 'http:', host: 'localhost:8000' } }, WebSocket: Socket,
    setTimeout: () => 1, clearTimeout: () => {} })
  wsService.connect()
  const old = sockets[0]
  wsService.disconnect()
  wsService.connect()
  sockets[1].onopen()
  old.onclose()
  assert.equal(states.at(-1), true)
  wsService.connect()
  assert.equal(sockets.length, 2)
})

test('API requests use the session cookie even if an old local token remains', async () => {
  let request
  const { api } = load('lib/api.ts', {}, {
    process: { env: {} },
    window: { location: { port: '8000' } },
    localStorage: { getItem: () => 'expired-legacy-token' },
    AbortSignal: { timeout: () => undefined },
    fetch: async (url, options) => { request = options; return { ok: true, json: async () => ({ ok: true }) } },
  })
  await api('/session')
  assert.equal(request.credentials, 'include')
  assert.equal(request.headers.Authorization, undefined)
})
