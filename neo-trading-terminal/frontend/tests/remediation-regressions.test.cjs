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
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    require: name => {
      if (!(name in dependencies)) throw new Error(name)
      return dependencies[name]
    },
    ...globals,
  })
  return module.exports
}

test('wsService.disconnect resets reconnecting flag so future reconnects still work', () => {
  const sockets = []
  let timers = []
  let nextId = 1

  class Socket {
    static OPEN = 1
    static CONNECTING = 0
    readyState = 0
    constructor() {
      sockets.push(this)
    }
    close() {}
  }

  const { wsService } = load(
    'services/ws.ts',
    {
      '@/lib/api': { apiBase: () => '' },
      '@/stores/marketStore': { useMarketStore: { getState: () => ({ setConnected: () => {} }) } },
    },
    {
      window: { location: { protocol: 'http:', host: 'localhost:8000' } },
      WebSocket: Socket,
      setTimeout: (fn, ms) => {
        const id = nextId++
        timers.push({ id, fn, ms, cleared: false })
        return id
      },
      clearTimeout: id => {
        const t = timers.find(item => item.id === id)
        if (t) t.cleared = true
      },
    }
  )

  // Connect and suffer an unexpected drop -> reconnect timer pending (reconnecting = true).
  wsService.connect()
  assert.equal(sockets.length, 1)
  sockets[0].onclose()
  assert.equal(timers.filter(t => !t.cleared).length, 1)

  // Intentional disconnect cancels timer and must clear reconnecting state.
  wsService.disconnect()
  assert.equal(timers[0].cleared, true)

  // Subsequent connect + unexpected close must schedule a new reconnect attempt!
  wsService.connect()
  assert.equal(sockets.length, 2)
  sockets[1].onopen()
  sockets[1].onclose()
  const pending = timers.filter(t => !t.cleared)
  assert.equal(pending.length, 1, 'Expected reconnect timer to be scheduled after prior disconnect')
})

test('index.tsx uses shared useQuotes, keeps { ids: [i.id] }, and separates error slots', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/pages/index.tsx'), 'utf8')
  assert.match(src, /useQuotes/, 'Markets page should use shared useQuotes hook')
  assert.doesNotMatch(src, /setInterval\s*\(/, 'Markets page must not duplicate ad-hoc setInterval quote polling')
  assert.match(src, /\{\s*ids:\s*\[\s*i\.id\s*\]\s*\}/, 'Watchlist POST must send { ids: [i.id] } matching QuoteRequest')
  assert.doesNotMatch(src, /setError\(''\)/, 'Markets page should track errors by concern so quote updates never wipe star/search errors')
})

test('useQuotes skips hidden-tab polling and triggers immediate refresh on visibility restore', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/lib/useQuotes.ts'), 'utf8')
  assert.match(src, /visibilityState\s*===\s*'hidden'/, 'useQuotes must pause polling when tab is hidden')
  assert.match(src, /visibilitychange/, 'useQuotes must refresh on visibilitychange')
  assert.match(src, /updatedAt:\s*string/, 'useQuotes must expose updatedAt timestamp')
})

test('strategies.tsx surfaces stop and pause failures to UI state instead of swallowing errors', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/pages/strategies.tsx'), 'utf8')
  assert.doesNotMatch(src, /console\.error\s*\(\s*e\s*\)/, 'strategies.tsx should surface action errors in UI rather than only logging')
  assert.match(src, /setActiveError\s*\(\s*failure\s*\(\s*e\s*\)\s*\)/, 'strategies.tsx must surface fetch/stop/pause failures via failure(e)')
  assert.match(src, /activeError\s*&&\s*<p className="error"/, 'strategies.tsx must render activeError alert')
})
