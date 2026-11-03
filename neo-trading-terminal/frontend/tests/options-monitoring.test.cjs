const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

test('monitor refreshes visible pages only and cleans up its timer and listener', () => {
  let tick, listener, cleared = false, removed = false, refreshes = 0
  const visibility = []
  const doc = { visibilityState: 'visible', addEventListener: (name, fn) => { listener = fn },
    removeEventListener: (name, fn) => { removed = fn === listener } }
  const module = { exports: {} }
  const source = fs.readFileSync(path.join(__dirname, '../src/lib/optionsMonitoring.ts'), 'utf8')
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
    { module, exports: module.exports, document: doc,
      setInterval: (fn, ms) => { assert.equal(ms, 60000); tick = fn; return 3 },
      clearInterval: id => { cleared = id === 3 } })
  const stop = module.exports.watchVisibleSnapshots(() => { refreshes++ }, visible => visibility.push(visible))
  tick()
  doc.visibilityState = 'hidden'; listener(); tick()
  assert.equal(refreshes, 1)
  assert.equal(visibility.at(-1), false)
  doc.visibilityState = 'visible'; listener(); tick()
  assert.equal(refreshes, 2)
  assert.equal(visibility.at(-1), true)
  stop()
  assert.ok(cleared && removed)
})
