const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const vm = require('node:vm')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
function load(file, overrides = {}, globals = {}) {
  const filename = path.join(__dirname, '../src', file)
  const mod = { exports: {} }
  const localRequire = name => {
    if (name in overrides) return overrides[name]
    if (name.startsWith('@/')) return load(name.slice(2) + (name.includes('/lib/') ? '.ts' : '.tsx'), overrides, globals)
    if (name.startsWith('.')) { const target = path.relative(path.join(__dirname, '../src'), path.resolve(path.dirname(filename), name)); return load(target + (target.endsWith('optionsPlatform') ? '.ts' : '.tsx'), overrides, globals) }
    return require(name)
  }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, { module: mod, exports: mod.exports, require: localRequire, console, setTimeout, clearTimeout, AbortController, DOMException, process, ...globals }, { filename })
  return mod.exports
}
const helpers = () => load('lib/optionsPlatform.ts', { './api': { apiBase: () => '' } })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function hookHarness() {
  const slots = []
  let cursor = 0, effects = []
  const react = {
    ...React,
    useState(initial) {
      const i = cursor++
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial
      return [slots[i], next => { slots[i] = typeof next === 'function' ? next(slots[i]) : next }]
    },
    useRef(value) { const i = cursor++; return slots[i] ??= { current: value } },
    useCallback(fn) { return fn },
    useEffect(fn) { effects.push(fn) },
  }
  return { react, render(fn, props) { cursor = 0; effects = []; return fn(props) }, effect(index) { return effects[index]() } }
}
function find(tree, predicate) {
  if (Array.isArray(tree)) return tree.map(child => find(child, predicate)).find(Boolean)
  if (!React.isValidElement(tree)) return undefined
  return predicate(tree) ? tree : find(tree.props.children, predicate)
}
const button = (tree, label) => find(tree, node => node.type === 'button' && node.props.children === label)

test('selected job fences a pending cancellation and suspends reads during mutation', async () => {
  const h = hookHarness(), readA = deferred(), cancelA = deferred()
  const requests = []
  const request = (url, method, body, channel) => {
    requests.push({ url, method, channel })
    if (method === 'POST') return cancelA.promise
    if (url === '/scans/A') return readA.promise
    return Promise.resolve({ id: 'B', status: 'completed', report: { key: 'B-evidence' } })
  }
  const cancelled = []
  const Jobs = load('components/options-platform/Jobs.tsx', { react: h.react, './Workspace': { useWorkspace: () => ({ request, cancel: value => cancelled.push(value), busy: false, selectReport() {} }) }, '@/lib/optionsPlatform': helpers() }).default
  const render = () => h.render(Jobs, { kind: 'scans', visible: true })
  const choose = value => find(render(), n => n.type === 'select').props.onChange({ target: { value } })
  choose('A')
  button(render(), 'Refresh selected job').props.onClick()
  const cancel = button(render(), 'Cancel selected job').props.onClick()
  button(render(), 'Refresh selected job').props.onClick()
  assert.equal(requests.filter(r => r.url === '/scans/A').length, 1)
  choose('B')
  button(render(), 'Refresh selected job').props.onClick()
  await Promise.resolve()
  cancelA.resolve({ id: 'A', status: 'cancelled', report: { key: 'A-cancel' } })
  readA.resolve({ id: 'A', status: 'queued', report: { key: 'A-stale-read' } })
  await cancel
  const evidence = find(render(), n => n.props.value?.report)
  assert.equal(evidence.props.value.report.key, 'B-evidence')
})

test('monitoring alert page and association context discard delayed previous responses', async () => {
  const h = hookHarness(), oldAlerts = deferred(), oldAssociation = deferred()
  let firstPageReads = 0
  const request = async url => {
    if (url.startsWith('/alerts?') && url.endsWith('=0')) {
      return ++firstPageReads === 1 ? Array.from({ length: 20 }, (_, i) => ({ id: `old-${i}` })) : oldAlerts.promise
    }
    if (url.startsWith('/alerts?')) return [{ id: 'new-alert' }]
    if (url.startsWith('/baselines?')) return [{ baseline_id: 'A' }, { baseline_id: 'B' }]
    if (url.startsWith('/baselines/A/')) return oldAssociation.promise
    if (url.startsWith('/baselines/B/')) return { id: 'new-association' }
  }
  const Monitoring = load('components/options-platform/Monitoring.tsx', { react: h.react, './Workspace': { useWorkspace: () => ({ request, cancel() {}, busy: false, selectReport() {} }) }, '@/lib/optionsPlatform': helpers() }).default
  const render = () => h.render(Monitoring, { visible: true })
  const click = label => button(render(), label).props.onClick()
  const settle = () => new Promise(resolve => setImmediate(resolve))
  click('Refresh monitoring and alerts'); await settle()
  click('Refresh monitoring and alerts'); await settle()
  click('Next alerts'); click('Refresh monitoring and alerts'); await settle()
  oldAlerts.resolve([{ id: 'late-alert' }]); await settle()
  assert.ok(find(render(), n => n.props.value?.id === 'new-alert'))
  assert.equal(find(render(), n => n.props.value?.id === 'late-alert'), undefined)
  click('Load saved baselines, owner evidence and ledgers'); await settle()
  const baseline = value => {
    const fields = find(render(), n => n.props.specs?.some(spec => spec.key === 'baseline'))
    fields.props.onChange({ ...fields.props.values, baseline: value })
  }
  baseline('A'); click('Load association history')
  baseline('B'); await click('Load association history')
  oldAssociation.resolve({ id: 'late-association' }); await settle()
  assert.ok(find(render(), n => n.props.value?.id === 'new-association'))
  assert.equal(find(render(), n => n.props.value?.id === 'late-association'), undefined)
})

test('workspace retains failed resource and conflict through unrelated successes', async () => {
  const h = hookHarness()
  class PlatformRequests {
    async request(path, method) {
      if (path === '/risk-policy' && method === 'PUT') throw new Error('Conflict: draft retained')
      if (path === '/alerts') throw new Error('Alerts unavailable')
      return { revision: 2 }
    }
    cancel() {}
    invalidate() {}
  }
  const overrides = { react: h.react, '@/components/Layout': { useTerminal: () => ({ user: { id: 7 } }) },
    '@/lib/optionsPlatform': { ...helpers(), PlatformRequests } }
  for (const name of ['Strategy', 'Monitoring', 'Jobs', 'Explanations']) overrides[`./${name}`] = { default: () => null }
  const Workspace = load('components/options-platform/Workspace.tsx', overrides, { Error, window: { addEventListener() {}, removeEventListener() {} } }).default
  const Owned = Workspace().type
  const render = () => h.render(Owned, {})
  const request = render().props.value.request
  const cleanup = h.effect(0)
  const alert = () => renderToStaticMarkup(find(render(), n => n.props.role === 'alert') ?? React.createElement('span'))
  try {
    await request('/risk-policy', 'PUT', {})
    await request('/alerts')
    await request('/monitoring')
    assert.match(alert(), /Conflict: draft retained/)
    assert.match(alert(), /Alerts unavailable/)
    await request('/risk-policy')
    assert.doesNotMatch(alert(), /Conflict/)
    assert.match(alert(), /Alerts unavailable/)
  } finally { cleanup() }
})

test('exact inventory and fill pages expose references beyond 100 and preserve checked IDs', async () => {
  const h = hookHarness()
  const inventory = Array.from({ length: 105 }, (_, i) => ({ row_id: `row-${i}`, exchange: 'NSE', token: i }))
  const fills = inventory.map((_, i) => ({ fill_id: `fill-${i}`, contract_id: `NSE|${i}` }))
  const request = async url => url.startsWith('/association-evidence?')
    ? [{ snapshot: { evidence_id: 'portfolio', sections: { positions: { rows: inventory } } }, fills: { fills } }]
    : undefined
  const Monitoring = load('components/options-platform/Monitoring.tsx', { react: h.react, './Workspace': { useWorkspace: () => ({ request, cancel() {}, busy: false, selectReport() {} }) }, '@/lib/optionsPlatform': helpers() }).default
  const render = () => h.render(Monitoring, { visible: false })
  button(render(), 'Load saved baselines, owner evidence and ledgers').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  const fields = find(render(), n => n.props.specs?.some(spec => spec.key === 'portfolio'))
  fields.props.onChange({ ...fields.props.values, portfolio: 'portfolio' })
  const choice = id => find(render(), n => n.type === 'label' && n.props.children?.includes?.(id)).props.children[0]
  choice('row-0').props.onChange()
  choice('fill-0').props.onChange()
  for (let page = 0; page < 5; page++) {
    for (const label of ['inventory rows', 'opening fills']) {
      const pager = find(render(), n => n.props.label === label && typeof n.props.onPage === 'function')
      pager.props.onPage(pager.props.offset + 20)
    }
  }
  choice('row-104').props.onChange()
  choice('fill-104').props.onChange()
  const selected = label => find(render(), n => n.props.label === label && n.props.ids)?.props.ids.join(',')
  assert.equal(selected('inventory rows'), 'row-0,row-104')
  assert.equal(selected('opening fills'), 'fill-0,fill-104')
})
test('decimal text preserves zero and precision, missing stays null, invalid amounts reject', () => {
  const { moneyText, integer } = helpers()
  assert.equal(moneyText('0'), '0'); assert.equal(moneyText('999999999999999.123456789012'), '999999999999999.123456789012'); assert.equal(moneyText('', true), null)
  for (const bad of ['NaN', '-1', '1e5', ' 2', '1.1234567890123']) assert.throws(() => moneyText(bad))
  assert.throws(() => integer('1.5')); assert.throws(() => integer('0')); assert.equal(integer('60', 60), 60)
})
test('rendered labelled fields invoke actual controlled selectors and preserve draft', () => {
  const { InputFields, Evidence } = load('components/options-platform/Forms.tsx', { '@/lib/optionsPlatform': helpers() })
  let next
  const tree = InputFields({ specs: [{ key: 'amount', label: 'Amount' }, { key: 'scope', label: 'Scope', options: [{ value: 'owned', label: 'Owned' }] }], values: { amount: '0', scope: '' }, onChange: value => { next = value } })
  const html = renderToStaticMarkup(tree)
  assert.match(html, /<label>Amount<input.*value="0"/); assert.match(html, /<label>Scope<select.*required/)
  tree.props.children[1].props.children[2].props.onChange({ target: { value: 'owned' } })
  assert.equal(next.scope, 'owned'); assert.equal(next.amount, '0')
  const evidence = renderToStaticMarkup(React.createElement(Evidence, { value: { pnl: null, costs: '0' } }))
  assert.match(evidence, /Unavailable/); assert.match(evidence, />0</)
})
test('late unauthorized response cannot expire a newer owner scope', async () => {
  let resolve, expired = 0
  const { PlatformRequests } = load('lib/optionsPlatform.ts', { './api': { apiBase: () => '' } }, { fetch: () => new Promise(r => { resolve = r }) })
  const client = new PlatformRequests('', () => expired++)
  const pending = client.request('/analyses'); client.invalidate()
  resolve({ ok: false, status: 401, json: async () => ({ detail: 'expired' }) })
  await assert.rejects(pending, e => e.name === 'AbortError'); assert.equal(expired, 0)
})
test('active unauthorized response expires once and conflict preserves actionable draft message', async () => {
  let status = 401, expired = 0
  const { PlatformRequests } = load('lib/optionsPlatform.ts', { './api': { apiBase: () => '' } }, { fetch: async () => ({ ok: false, status, json: async () => ({ detail: 'denied' }) }) })
  const client = new PlatformRequests('', () => expired++)
  await assert.rejects(client.request('/risk-policy')); assert.equal(expired, 1)
  status = 409; await assert.rejects(client.request('/risk-policy', 'PUT', { revision: 1 }), /draft retained.*Reload/)
})
test('same-channel supersession aborts old request before state delivery', async () => {
  const pending = []
  const { PlatformRequests } = load('lib/optionsPlatform.ts', { './api': { apiBase: () => '' } }, { fetch: (url, init) => new Promise(resolve => pending.push({ resolve, init })) })
  const client = new PlatformRequests('', () => {})
  const old = client.request('/scans/old', 'GET', undefined, 'selected-job'), current = client.request('/scans/new', 'GET', undefined, 'selected-job')
  assert.equal(pending[0].init.signal.aborted, true)
  pending[0].resolve({ ok: true, json: async () => ({ id: 'old' }) }); pending[1].resolve({ ok: true, json: async () => ({ id: 'new' }) })
  await assert.rejects(old, e => e.name === 'AbortError'); assert.equal((await current).id, 'new')
})
test('scanner renders required criteria and explicit start control', () => {
  const Jobs = load('components/options-platform/Jobs.tsx', { './Workspace': { useWorkspace: () => ({ request: async () => undefined, busy: false, selectReport() {} }) }, '@/lib/optionsPlatform': helpers() }).default
  const html = renderToStaticMarkup(React.createElement(Jobs, { kind: 'scans', visible: true }))
  assert.match(html, /Minimum volume/); assert.match(html, /Maximum relative spread/); assert.match(html, /Start scan/); assert.match(html, /required/)
})
test('visible job polling pauses, aborts hidden request, resumes and cleans up', () => {
  let tick, listener, refreshes = 0, cancelled = 0, removed = false
  const document = { visibilityState: 'visible', addEventListener: (_, fn) => { listener = fn }, removeEventListener: (_, fn) => { removed = fn === listener } }
  const { watchPlatformJob } = load('lib/optionsPlatform.ts', { './api': { apiBase: () => '' } }, { document, setTimeout: () => 1, clearTimeout() {}, setInterval: fn => { tick = fn; return 2 }, clearInterval() {} })
  const stop = watchPlatformJob(() => refreshes++, () => cancelled++)
  tick(); assert.equal(refreshes, 1)
  document.visibilityState = 'hidden'; listener(); tick(); assert.equal(refreshes, 1); assert.equal(cancelled, 1)
  document.visibilityState = 'visible'; listener(); assert.equal(refreshes, 2)
  stop(); assert.equal(cancelled, 2); assert.equal(removed, true)
})
test('selected context cancellation rejects late401 without auth side effects', async () => {
  let resolve, expired = 0
  const { PlatformRequests } = load('lib/optionsPlatform.ts', { './api': { apiBase: () => '' } }, { fetch: () => new Promise(r => { resolve = r }) })
  const client = new PlatformRequests('', () => expired++)
  const pending = client.request('/explain', 'POST', {}, 'explanation'); client.cancel('explanation')
  resolve({ ok: false, status: 401, json: async () => ({ detail: 'expired' }) })
  await assert.rejects(pending, e => e.name === 'AbortError'); assert.equal(expired, 0)
})
test('rendered strategy has unavailable server selectors, explicit quantity and disabled analysis', () => {
  const Strategy = load('components/options-platform/Strategy.tsx', { './Workspace': { useWorkspace: () => ({ request: async () => undefined, cancel() {}, busy: false, selectReport() {} }) }, '@/lib/optionsPlatform': helpers() }).default
  const html = renderToStaticMarkup(React.createElement(Strategy))
  assert.match(html, /Equity contract<select/); assert.match(html, /Quantity \(units\)/); assert.match(html, /disabled=""[^>]*>Analyze selected contracts/); assert.match(html, /No server evidence selected/)
})
test('rendered historical form requires explicit schedule, costs, fill policy and dataset', () => {
  const BacktestForm = load('components/options-platform/BacktestForm.tsx', { './Workspace': { useWorkspace: () => ({ request: async () => undefined, busy: false }) }, '@/lib/optionsPlatform': helpers() }).default
  const html = renderToStaticMarkup(React.createElement(BacktestForm, { datasets: [{ id: 'data', status: 'validated', dataset_status: 'synthetic', row_count: 3 }], onStarted() {} }))
  assert.match(html, /Decision timestamp with offset/); assert.match(html, /Opening fee INR per leg/); assert.match(html, /depth required/); assert.match(html, /data · synthetic · 3 rows/); assert.match(html, /Start backtest/)
})
test('rendered complete FIFO and equity forms distinguish user declarations and cashflows', () => {
  const Monitoring = load('components/options-platform/Monitoring.tsx', { './Workspace': { useWorkspace: () => ({ request: async () => undefined, busy: false, selectReport() {} }) }, '@/lib/optionsPlatform': helpers() }).default
  const html = renderToStaticMarkup(React.createElement(Monitoring, { visible: false }))
  assert.match(html, /Complete ledger JSON/); assert.match(html, /Never broker-verified/); assert.match(html, /coverage_end/); assert.match(html, /External flow INR \(signed\)/); assert.match(html, /Mark.*fill|mark-versus-selected-fill/)
})
