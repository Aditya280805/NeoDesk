const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const FIXTURES_DIR = path.resolve(__dirname, '../../backend/evals/fixtures/specialist_api')
function readFixture(name) {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, name), 'utf8'))
}

const chainFixture = readFixture('chain.json')
const portfolioFixture = readFixture('portfolio.json')
const riskFixture = readFixture('risk.json')
const clarifyFixture = readFixture('clarify.json')
const scopeChangeFixture = readFixture('scope_change.json')

const deferred = () => {
  let resolve, reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const settle = () => new Promise(resolve => setImmediate(resolve))

function loadTs(relPath, overrides = {}, globals = {}) {
  const filename = path.join(__dirname, '../src', relPath)
  const mod = { exports: {} }
  const source = fs.readFileSync(filename, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
  }).outputText
  const localRequire = name => {
    if (name in overrides) return overrides[name]
    if (name.startsWith('@/')) {
      const sub = name.slice(2)
      for (const ext of ['.ts', '.tsx']) {
        if (fs.existsSync(path.join(__dirname, '../src', sub + ext))) {
          return loadTs(sub + ext, overrides, globals)
        }
      }
    }
    if (name.startsWith('./') || name.startsWith('../')) {
      const base = path.resolve(path.dirname(filename), name)
      for (const ext of ['.ts', '.tsx']) {
        if (fs.existsSync(base + ext)) {
          return loadTs(path.relative(path.join(__dirname, '../src'), base + ext), overrides, globals)
        }
      }
    }
    return require(name)
  }
  vm.runInNewContext(
    compiled,
    {
      module: mod,
      exports: mod.exports,
      require: localRequire,
      console,
      process,
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      AbortController,
      AbortSignal,
      DOMException,
      Event,
      ...globals,
    },
    { filename }
  )
  return mod.exports
}

function depsChanged(prev, next) {
  if (!prev || !next) return true
  if (prev.length !== next.length) return true
  return next.some((v, i) => !Object.is(v, prev[i]))
}

function createHarness(options = {}) {
  const slots = []
  const effectRecords = []
  const events = new Map()
  const intervals = new Set()
  const requests = []
  const responseQueue = []
  let monitorWatcherCalls = []
  let cursor = 0
  let pendingEffects = []

  const hooks = {
    ...React,
    useState(initial) {
      const i = cursor++
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial
      return [
        slots[i],
        next => {
          slots[i] = typeof next === 'function' ? next(slots[i]) : next
        },
      ]
    },
    useRef(initial) {
      const i = cursor++
      if (!(i in slots)) slots[i] = { current: initial }
      return slots[i]
    },
    useCallback(fn, deps) {
      const i = cursor++
      const rec = slots[i]
      if (!rec || depsChanged(rec.deps, deps)) {
        slots[i] = { fn, deps }
      }
      return slots[i].fn
    },
    useEffect(fn, deps) {
      const i = cursor++
      const rec = effectRecords[i]
      if (!rec || deps === undefined || depsChanged(rec.deps, deps)) {
        pendingEffects.push({ i, fn, deps, prevCleanup: rec?.cleanup })
      }
    },
  }

  const fakeWindow = {
    location: { port: '8000', protocol: 'http:', hostname: '127.0.0.1' },
    addEventListener(name, fn) {
      events.set(name, fn)
    },
    removeEventListener(name) {
      events.delete(name)
    },
    dispatchEvent(event) {
      events.get(event.type)?.(event)
    },
  }

  const fakeDoc = {
    visibilityState: 'visible',
    addEventListener() {},
    removeEventListener() {},
  }

  const fakeFetch = async (url, init = {}) => {
    const parsedBody = init.body ? JSON.parse(init.body) : undefined
    requests.push({ url, method: init.method || 'GET', body: parsedBody, signal: init.signal })
    const entry = responseQueue.shift()
    if (!entry) throw new Error(`Unexpected fetch: ${init.method || 'GET'} ${url}`)
    const result = typeof entry === 'function' ? await entry({ url, method: init.method || 'GET', body: parsedBody, signal: init.signal }) : entry
    if (result instanceof Error) throw result
    const status = result.status ?? 200
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => result.data,
    }
  }

  const sharedGlobals = {
    process: { env: {} },
    window: fakeWindow,
    document: fakeDoc,
    fetch: fakeFetch,
    setInterval: (fn, ms) => {
      const id = setInterval(fn, ms)
      intervals.add(id)
      return id
    },
    clearInterval: id => {
      intervals.delete(id)
      clearInterval(id)
    },
  }

  const apiMod = loadTs('lib/api.ts', {}, sharedGlobals)
  const portfolioEvidenceMod = loadTs('lib/portfolioEvidence.ts', {}, sharedGlobals)
  const portfolioRiskMod = loadTs('lib/portfolioRisk.ts', { './portfolioEvidence': portfolioEvidenceMod }, sharedGlobals)
  const PortfolioEvidence = loadTs('components/PortfolioEvidence.tsx', {
    react: React,
    '@/lib/portfolioEvidence': portfolioEvidenceMod,
  }, sharedGlobals).default
  const PortfolioRiskPanel = loadTs('components/PortfolioRiskPanel.tsx', {
    react: React,
    '@/lib/portfolioRisk': portfolioRiskMod,
  }, sharedGlobals).default

  const monitoringMod = {
    watchVisibleSnapshots(refresh, onVisibility) {
      monitorWatcherCalls.push({ active: true })
      const idx = monitorWatcherCalls.length - 1
      onVisibility?.(true)
      return () => {
        monitorWatcherCalls[idx].active = false
      }
    },
  }

  const PortfolioRiskSettings = ({ onRevision }) => {
    hooks.useEffect(() => {
      onRevision?.(0)
    }, [onRevision])
    return React.createElement('section', { 'data-testid': 'risk-settings', className: 'portfolio-risk-settings' }, 'Portfolio risk policy')
  }

  const Icon = () => null
  const Link = ({ href, children, ...props }) => React.createElement('a', { href, ...props }, children)
  const OptionsChat = loadTs('pages/options-chat.tsx', {
    react: hooks,
    'next/link': { __esModule: true, default: Link },
    'lucide-react': { __esModule: true, MessageCircle: Icon, RefreshCw: Icon, Send: Icon, ShieldCheck: Icon },
    '@/lib/api': apiMod,
    '@/lib/optionsMonitoring': options.realMonitoring
      ? loadTs('lib/optionsMonitoring.ts', {}, sharedGlobals)
      : monitoringMod,
    '@/lib/portfolioEvidence': portfolioEvidenceMod,
    '@/lib/portfolioRisk': portfolioRiskMod,
    '@/components/PortfolioEvidence': { __esModule: true, default: PortfolioEvidence },
    '@/components/PortfolioRiskPanel': { __esModule: true, default: PortfolioRiskPanel },
    '@/components/PortfolioRiskSettings': { __esModule: true, default: PortfolioRiskSettings },
  }, sharedGlobals).default

  function render() {
    cursor = 0
    pendingEffects = []
    const tree = OptionsChat()
    for (const eff of pendingEffects) {
      eff.prevCleanup?.()
      const cleanup = eff.fn()
      effectRecords[eff.i] = { deps: eff.deps, cleanup }
    }
    return tree
  }

  function unmount() {
    for (const rec of effectRecords) {
      rec?.cleanup?.()
    }
    for (const id of intervals) clearInterval(id)
    intervals.clear()
  }

  return {
    render,
    unmount,
    requests,
    monitorWatcherCalls,
    queue: (...items) => responseQueue.push(...items),
    expire: () => fakeWindow.dispatchEvent(new Event('neodesk:session-expired')),
    html: tree => renderToStaticMarkup(tree),
  }
}

function treeNodes(node) {
  if (Array.isArray(node)) return node.flatMap(treeNodes)
  if (!node || typeof node !== 'object') return []
  return [node, ...treeNodes(node.props?.children)]
}

function textOf(node) {
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  return textOf(node.props?.children)
}

function findScopeSelect(tree) {
  return treeNodes(tree).find(n => n.type === 'select' && n.props['aria-label'] === 'Chat scope')
}

function findInputByLabel(tree, labelPrefix) {
  const label = treeNodes(tree).find(n => n.type === 'label' && textOf(n).startsWith(labelPrefix))
  if (!label) return undefined
  return treeNodes(label).find(n => n.type === 'input' || n.type === 'select')
}

function findTextarea(tree) {
  return treeNodes(tree).find(n => n.type === 'textarea')
}

function findForm(tree) {
  return treeNodes(tree).find(n => n.type === 'form' && treeNodes(n).some(c => c.type === 'textarea'))
}

function findButton(tree, label) {
  return treeNodes(tree).find(n => n.type === 'button' && (textOf(n) === label || n.props['aria-label'] === label))
}

function findMonitoringCheckbox(tree) {
  return treeNodes(tree).find(n => n.type === 'input' && n.props.type === 'checkbox')
}

const readyStatus = () => ({
  status: 200,
  data: {
    configured: true,
    model_configured: true,
    mcp_ready: true,
    enabled: true,
    provider: 'openai',
    api_key_env: 'OPENAI_API_KEY',
    setup_error: null,
    model: 'gpt-4.1-mini',
    read_only: true,
  },
})

test('explicit Options and trading mode calls chain endpoint and renders chain evidence only', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    const select = findScopeSelect(tree)
    assert.ok(select)
    const optionValues = treeNodes(select).filter(n => n.type === 'option').map(n => ({ value: n.props.value, text: textOf(n) }))
    assert.ok(optionValues.some(o => o.value === 'chain' && /Options and trading/i.test(o.text)))
    assert.ok(optionValues.some(o => o.value === 'portfolio' && /Portfolio analysis/i.test(o.text)))
    assert.ok(optionValues.some(o => o.value === 'risk' && /Portfolio risk/i.test(o.text)))
    assert.ok(optionValues.some(o => o.value === 'auto' && /Auto-select/i.test(o.text)))

    select.props.onChange({ target: { value: 'chain' } })
    tree = h.render()
    findInputByLabel(tree, 'Underlying').props.onChange({ target: { value: chainFixture.request.underlying } })
    tree = h.render()
    findInputByLabel(tree, 'Exchange').props.onChange({ target: { value: chainFixture.request.exchange } })
    tree = h.render()
    findInputByLabel(tree, 'Expiry').props.onChange({ target: { value: chainFixture.request.expiry } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: chainFixture.request.message } })
    tree = h.render()

    h.queue({ status: chainFixture.status_code, data: chainFixture.response })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const chatCalls = h.requests.filter(r => r.url.includes('/chat'))
    assert.equal(chatCalls.length, 1)
    assert.equal(chatCalls[0].url, '/api' + chainFixture.endpoint.replace(/^\/api/, ''))
    assert.equal(chatCalls[0].body.message, chainFixture.request.message)
    assert.equal(chatCalls[0].body.underlying, chainFixture.request.underlying)
    assert.equal(chatCalls[0].body.exchange, chainFixture.request.exchange)
    assert.equal(chatCalls[0].body.expiry, chainFixture.request.expiry)

    const html = h.html(h.render())
    assert.match(html, new RegExp(chainFixture.response.answer.slice(0, 40)))
    assert.match(html, /options_trading_analysis/)
    assert.match(html, /scope: chain/i)
    assert.match(html, /Kotak snapshot · NIFTY · 26Nov2026/)
    assert.doesNotMatch(html, /portfolio-evidence/)
    assert.doesNotMatch(html, /portfolio-risk/)
  } finally {
    h.unmount()
  }
})

test('explicit Portfolio analysis mode calls portfolio endpoint and renders PortfolioEvidence without risk findings', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'portfolio' } })
    tree = h.render()
    assert.equal(findInputByLabel(tree, 'Underlying'), undefined)
    assert.doesNotMatch(h.html(tree), /data-testid="risk-settings"/)

    findTextarea(tree).props.onChange({ target: { value: portfolioFixture.request.message } })
    tree = h.render()

    h.queue({ status: portfolioFixture.status_code, data: portfolioFixture.response })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const chatCalls = h.requests.filter(r => r.url.includes('/chat'))
    assert.equal(chatCalls.length, 1)
    assert.equal(chatCalls[0].url, '/api' + portfolioFixture.endpoint.replace(/^\/api/, ''))
    assert.deepEqual(chatCalls[0].body, { message: portfolioFixture.request.message })

    const html = h.html(h.render())
    assert.match(html, /100000\.00/)
    assert.match(html, /portfolio_analysis/)
    assert.match(html, /scope: portfolio/i)
    assert.match(html, new RegExp(portfolioFixture.response.evidence_ids[0]))
    assert.match(html, /portfolio-evidence/)
    assert.doesNotMatch(html, /portfolio-risk/)
    assert.doesNotMatch(html, /Risk assessment/)
  } finally {
    h.unmount()
  }
})

test('explicit Portfolio risk mode calls risk endpoint and renders PortfolioRiskPanel without account sections', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'risk' } })
    tree = h.render()
    assert.equal(findInputByLabel(tree, 'Underlying'), undefined)
    assert.match(h.html(tree), /data-testid="risk-settings"/)

    findTextarea(tree).props.onChange({ target: { value: riskFixture.request.message } })
    tree = h.render()

    h.queue({ status: riskFixture.status_code, data: riskFixture.response })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const chatCalls = h.requests.filter(r => r.url.includes('/chat'))
    assert.equal(chatCalls.length, 1)
    assert.equal(chatCalls[0].url, '/api' + riskFixture.endpoint.replace(/^\/api/, ''))
    assert.deepEqual(chatCalls[0].body, { message: riskFixture.request.message })

    const html = h.html(h.render())
    assert.match(html, /portfolio_risk/)
    assert.match(html, /scope: risk/i)
    assert.match(html, /portfolio-risk/)
    assert.match(html, /Risk assessment/)
    assert.match(html, new RegExp(riskFixture.response.risk_report_ids[0]))
    assert.match(html, new RegExp(riskFixture.response.evidence_ids[0]))
    assert.doesNotMatch(html, /portfolio-evidence/)
    assert.doesNotMatch(html, /Portfolio summaries/)
  } finally {
    h.unmount()
  }
})

test('Auto-select routes chain, portfolio, and risk in one request each and activates concrete refresh only after routing', async () => {
  for (const [scopeName, fixture, expectedPattern, forbiddenPattern] of [
    ['chain', chainFixture, /Kotak snapshot · NIFTY · 26Nov2026/, /portfolio-evidence|portfolio-risk/],
    ['portfolio', portfolioFixture, /portfolio-evidence/, /portfolio-risk|Risk assessment/],
    ['risk', riskFixture, /portfolio-risk/, /portfolio-evidence|Portfolio summaries/],
  ]) {
    const h = createHarness()
    try {
      h.queue(readyStatus())
      h.render()
      await settle()

      let tree = h.render()
      findScopeSelect(tree).props.onChange({ target: { value: 'auto' } })
      tree = h.render()

      // Before concrete scope exists, snapshot refresh and periodic monitoring are disabled.
      assert.equal(findButton(tree, 'Refresh snapshot').props.disabled, true)
      assert.equal(findMonitoringCheckbox(tree).props.disabled, true)

      findTextarea(tree).props.onChange({ target: { value: fixture.request.message } })
      tree = h.render()

      h.queue({
        status: 200,
        data: { scope: scopeName, ...fixture.response },
      })
      await findForm(tree).props.onSubmit({ preventDefault() {} })
      await settle()

      const unifiedCalls = h.requests.filter(r => r.url === '/api/options-agent/unified-chat')
      assert.equal(unifiedCalls.length, 1)
      assert.equal(unifiedCalls[0].body.message, fixture.request.message)

      tree = h.render()
      const html = h.html(tree)
      assert.match(html, new RegExp(fixture.response.agent_id))
      assert.match(html, new RegExp(`scope: ${scopeName}`, 'i'))
      assert.match(html, expectedPattern)
      assert.doesNotMatch(html, forbiddenPattern)

      // Once routed to a concrete scope, snapshot refresh & monitoring are enabled.
      assert.equal(findButton(tree, 'Refresh snapshot').props.disabled, false)
      assert.equal(findMonitoringCheckbox(tree).props.disabled, false)
    } finally {
      h.unmount()
    }
  }
})

test('Auto-select clarify renders text only, creates no specialist conversation, and keeps refresh disabled', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'auto' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: clarifyFixture.request.message } })
    tree = h.render()

    h.queue({ status: clarifyFixture.status_code, data: clarifyFixture.response })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    tree = h.render()
    const html = h.html(tree)
    assert.match(html, new RegExp(clarifyFixture.response.answer.slice(0, 35)))
    assert.match(html, /master_router/)
    assert.match(html, /scope: clarify/i)
    assert.doesNotMatch(html, /options-evidence/)
    assert.doesNotMatch(html, /portfolio-evidence/)
    assert.doesNotMatch(html, /portfolio-risk/)
    assert.doesNotMatch(html, /Kotak snapshot/)
    assert.doesNotMatch(html, /Cited evidence/)
    assert.equal(findButton(tree, 'Refresh snapshot').props.disabled, true)
    assert.equal(findMonitoringCheckbox(tree).props.disabled, true)

    // Follow-up after clarify must not send any conversation_id.
    findTextarea(tree).props.onChange({ target: { value: portfolioFixture.request.message } })
    tree = h.render()
    h.queue({ status: 200, data: { scope: 'portfolio', ...portfolioFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const unifiedCalls = h.requests.filter(r => r.url === '/api/options-agent/unified-chat')
    assert.equal(unifiedCalls.length, 2)
    assert.equal(unifiedCalls[1].body.conversation_id ?? null, null)
  } finally {
    h.unmount()
  }
})

test('HTTP 409 conversation_scope_changed preserves draft, retains conversation until New chat confirmation, and never auto-resubmits', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'auto' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: chainFixture.request.message } })
    tree = h.render()

    const initialCid = scopeChangeFixture.request.conversation_id
    h.queue({
      status: 200,
      data: { scope: 'chain', ...chainFixture.response, conversation_id: initialCid },
    })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    // Now send scope-changing follow-up.
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: scopeChangeFixture.request.message } })
    tree = h.render()

    h.queue({
      status: scopeChangeFixture.status_code,
      data: scopeChangeFixture.response,
    })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    tree = h.render()
    const requestsBeforeConfirm = h.requests.length
    assert.equal(requestsBeforeConfirm, 3) // status + turn 1 + 409 turn 2 (NO automatic retry)

    // Draft preserved in textarea, prior turn retained until user confirms New chat.
    assert.equal(findTextarea(tree).props.value, scopeChangeFixture.request.message)
    const alert = treeNodes(tree).find(n => n.props?.role === 'alert')
    assert.ok(alert, 'Expected scope-change alert')
    assert.match(textOf(alert), new RegExp(scopeChangeFixture.response.detail.message))
    assert.match(h.html(tree), new RegExp(chainFixture.response.answer.slice(0, 30)))

    const newChatInAlert = findButton(alert, 'New chat')
    assert.ok(newChatInAlert, 'Expected New chat action button inside scope-change alert')
    newChatInAlert.props.onClick()
    await settle()

    // Still no auto-resubmission!
    assert.equal(h.requests.length, requestsBeforeConfirm)

    tree = h.render()
    // Incompatible conversation state cleared, draft preserved.
    assert.equal(findTextarea(tree).props.value, scopeChangeFixture.request.message)
    assert.doesNotMatch(h.html(tree), new RegExp(chainFixture.response.answer.slice(0, 30)))
    assert.equal(findMonitoringCheckbox(tree).props.disabled, true)

    // Manual resubmission now creates a fresh conversation without old conversation_id.
    h.queue({ status: 200, data: { scope: 'risk', ...riskFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const lastCall = h.requests.at(-1)
    assert.equal(lastCall.url, '/api/options-agent/unified-chat')
    assert.equal(lastCall.body.conversation_id ?? null, null)
    assert.equal(lastCall.body.message, scopeChangeFixture.request.message)
  } finally {
    h.unmount()
  }
})

test('switching specialist during a pending request cancels busy state and suppresses late response and late error', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'portfolio' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: portfolioFixture.request.message } })
    tree = h.render()

    const pendingPortfolio = deferred()
    h.queue(() => pendingPortfolio.promise)
    const submitPromise = findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    // While pending, switch mode to risk.
    tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'risk' } })
    tree = h.render()
    assert.equal(findTextarea(tree).props.disabled, false)

    // Submit risk question while old portfolio request is still pending!
    findTextarea(tree).props.onChange({ target: { value: riskFixture.request.message } })
    tree = h.render()
    const pendingRisk = deferred()
    h.queue(() => pendingRisk.promise)
    const riskSubmitPromise = findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    // Resolve stale portfolio response FIRST while risk is still in flight.
    pendingPortfolio.resolve({ status: 200, data: portfolioFixture.response })
    await submitPromise
    await settle()

    tree = h.render()
    // Risk request must STILL be busy, and stale portfolio evidence must NOT appear.
    assert.equal(findTextarea(tree).props.disabled, true)
    assert.doesNotMatch(h.html(tree), /portfolio-evidence/)
    assert.doesNotMatch(h.html(tree), new RegExp(portfolioFixture.response.answer.slice(0, 30)))

    // Now resolve risk response.
    pendingRisk.resolve({ status: 200, data: riskFixture.response })
    await riskSubmitPromise
    await settle()

    tree = h.render()
    assert.equal(findTextarea(tree).props.disabled, false)
    const html = h.html(tree)
    assert.match(html, /portfolio-risk/)
    assert.match(html, new RegExp(riskFixture.response.risk_report_ids[0]))
    assert.doesNotMatch(html, /portfolio-evidence/)
  } finally {
    h.unmount()
  }
})

test('late error and late snapshot response from previous mode do not leak after mode switch', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    // Trigger pending erroring chat in chain mode, switch to portfolio before it rejects.
    let tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: chainFixture.request.message } })
    tree = h.render()
    const pendingErr = deferred()
    h.queue(() => pendingErr.promise)
    const errPromise = findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    findScopeSelect(h.render()).props.onChange({ target: { value: 'portfolio' } })
    pendingErr.resolve({ status: 503, data: { detail: 'Stale chain error must not show' } })
    await errPromise
    await settle()

    assert.doesNotMatch(h.html(h.render()), /Stale chain error must not show/)

    // Trigger pending snapshot refresh in portfolio mode, switch to risk before it resolves.
    const pendingSnap = deferred()
    h.queue(() => pendingSnap.promise)
    const snapPromise = findButton(h.render(), 'Refresh snapshot').props.onClick()
    await settle()

    findScopeSelect(h.render()).props.onChange({ target: { value: 'risk' } })
    pendingSnap.resolve({ status: 200, data: portfolioFixture.response.portfolio_snapshot })
    await snapPromise
    await settle()

    const html = h.html(h.render())
    assert.doesNotMatch(html, /portfolio-evidence/)
    assert.doesNotMatch(html, new RegExp(portfolioFixture.response.portfolio_snapshot.evidence_id))

    // Now test explicit portfolio refresh renders PortfolioEvidence without RiskPanel,
    // and explicit risk refresh renders RiskPanel without PortfolioEvidence.
    findScopeSelect(h.render()).props.onChange({ target: { value: 'portfolio' } })
    h.queue({ status: 200, data: portfolioFixture.response.portfolio_snapshot })
    await findButton(h.render(), 'Refresh snapshot').props.onClick()
    await settle()
    const portAsideHtml = h.html(h.render())
    assert.match(portAsideHtml, /portfolio-evidence/)
    assert.doesNotMatch(portAsideHtml, /portfolio-risk/)

    findScopeSelect(h.render()).props.onChange({ target: { value: 'risk' } })
    h.queue({
      status: 200,
      data: { ...portfolioFixture.response.portfolio_snapshot, risk_report: riskFixture.response.risk_snapshot.risk_report },
    })
    await findButton(h.render(), 'Refresh snapshot').props.onClick()
    await settle()
    const riskAsideHtml = h.html(h.render())
    assert.match(riskAsideHtml, /portfolio-risk/)
    assert.doesNotMatch(riskAsideHtml, /portfolio-evidence/)
  } finally {
    h.unmount()
  }
})

test('Auto-select rejects invalid or incomplete specialist payloads safely without partial evidence', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'auto' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: 'Check risk' } })
    tree = h.render()

    h.queue({
      status: 200,
      data: { scope: 'risk', agent_id: 'portfolio_risk', answer: 'Missing risk report', conversation_id: 'cid-bad' },
    })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    tree = h.render()
    const html = h.html(tree)
    assert.match(html, /role="alert"/)
    assert.doesNotMatch(html, /Missing risk report/)
    assert.doesNotMatch(html, /portfolio-risk/)
    assert.equal(findMonitoringCheckbox(tree).props.disabled, true)
  } finally {
    h.unmount()
  }
})

test('follow-up sends conversation_id and monitoring watcher stops on mode switch or New chat', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'auto' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: portfolioFixture.request.message } })
    tree = h.render()

    h.queue({ status: 200, data: { scope: 'portfolio', ...portfolioFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    tree = h.render()
    h.queue({ status: 200, data: portfolioFixture.response.portfolio_snapshot })
    findMonitoringCheckbox(tree).props.onChange({ target: { checked: true } })
    await settle()
    h.render()
    assert.equal(h.monitorWatcherCalls.length, 1)
    assert.equal(h.monitorWatcherCalls[0].active, true)

    findTextarea(h.render()).props.onChange({ target: { value: 'Follow-up on positions' } })
    tree = h.render()
    h.queue({ status: 200, data: { scope: 'portfolio', ...portfolioFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const chatCalls = h.requests.filter(r => r.url === '/api/options-agent/unified-chat')
    assert.equal(chatCalls.length, 2)
    assert.equal(chatCalls[0].body.conversation_id, undefined)
    assert.equal(chatCalls[1].body.conversation_id, portfolioFixture.response.conversation_id)

    findButton(h.render(), 'New chat').props.onClick()
    await settle()
    h.render()
    assert.equal(h.monitorWatcherCalls[0].active, false)
    assert.equal(findMonitoringCheckbox(h.render()).props.disabled, true)
  } finally {
    h.unmount()
  }
})

test('Auto follow-up clarify retains active conversation_id and rejects spurious conversation_id on initial clarify', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    // Part A: establish an Auto portfolio conversation, then receive a follow-up clarify.
    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'auto' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: portfolioFixture.request.message } })
    tree = h.render()

    h.queue({ status: 200, data: { scope: 'portfolio', ...portfolioFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    // Follow-up triggers clarify; backend echoes the existing conversation_id.
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: 'And what about both?' } })
    tree = h.render()
    const followUpClarify = {
      ...clarifyFixture.response,
      conversation_id: portfolioFixture.response.conversation_id,
    }
    h.queue({ status: 200, data: followUpClarify })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    // Prior portfolio evidence remains, and the clarify turn did not add new evidence.
    tree = h.render()
    assert.match(h.html(tree), /portfolio-evidence/)

    // Turn 3 must STILL send the original conversation_id (not null/undefined).
    findTextarea(tree).props.onChange({ target: { value: 'Specifically my holdings please' } })
    tree = h.render()
    h.queue({ status: 200, data: { scope: 'portfolio', ...portfolioFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const unifiedCalls = h.requests.filter(r => r.url === '/api/options-agent/unified-chat')
    assert.equal(unifiedCalls.length, 3)
    assert.equal(unifiedCalls[1].body.conversation_id, portfolioFixture.response.conversation_id)
    assert.equal(unifiedCalls[2].body.conversation_id, portfolioFixture.response.conversation_id)

    // Part B: fresh clarify after New chat must reject a non-null conversation_id from a misbehaving server.
    findButton(h.render(), 'New chat').props.onClick()
    await settle()
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: 'Help?' } })
    tree = h.render()
    h.queue({
      status: 200,
      data: { ...clarifyFixture.response, conversation_id: 'cid-should-not-exist-on-fresh-clarify' },
    })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const html = h.html(h.render())
    assert.match(html, /role="alert"/)
    assert.doesNotMatch(html, /Please ask separately/)
  } finally {
    h.unmount()
  }
})

test('validateReply rejects mismatched agent_id, non-read-only replies, blank answers, mid-conversation scope flips, and partial/leaky evidence', async () => {
  const cases = [
    {
      name: 'wrong agent_id in explicit chain mode',
      mode: 'chain',
      payload: { ...chainFixture.response, agent_id: 'portfolio_analysis' },
    },
    {
      name: 'read_only false in explicit chain mode',
      mode: 'chain',
      payload: { ...chainFixture.response, read_only: false },
    },
    {
      name: 'whitespace-only answer in explicit chain mode',
      mode: 'chain',
      payload: { ...chainFixture.response, answer: '   \n\t  ' },
    },
    {
      name: 'portfolio_snapshot missing summary and limitations',
      mode: 'portfolio',
      payload: {
        ...portfolioFixture.response,
        portfolio_snapshot: {
          ...portfolioFixture.response.portfolio_snapshot,
          summary: undefined,
          limitations: undefined,
        },
      },
    },
    {
      name: 'portfolio response leaking risk_report',
      mode: 'portfolio',
      payload: {
        ...portfolioFixture.response,
        risk_report: riskFixture.response.risk_snapshot.risk_report,
      },
    },
    {
      name: 'risk_snapshot missing coverage/findings/observation_times (render crash guard)',
      mode: 'risk',
      payload: {
        ...riskFixture.response,
        risk_snapshot: {
          evidence_id: riskFixture.response.risk_snapshot.evidence_id,
          risk_report: { report_id: 'r-partial', evaluated_at: '2026-11-11T10:34:12Z', summary: 'pass' },
        },
      },
    },
  ]

  for (const tc of cases) {
    const h = createHarness()
    try {
      h.queue(readyStatus())
      h.render()
      await settle()

      let tree = h.render()
      findScopeSelect(tree).props.onChange({ target: { value: tc.mode } })
      tree = h.render()
      findTextarea(tree).props.onChange({ target: { value: 'Run check' } })
      tree = h.render()

      h.queue({ status: 200, data: tc.payload })
      await findForm(tree).props.onSubmit({ preventDefault() {} })
      await settle()

      // Must render cleanly with role="alert" (not throw during renderToStaticMarkup) and omit broken evidence.
      const html = h.html(h.render())
      assert.match(html, /role="alert"/, `${tc.name}: expected validation error alert`)
      assert.doesNotMatch(html, /class="portfolio-risk"|Portfolio risk assessment/, `${tc.name}: risk panel must not render`)
      assert.doesNotMatch(html, /portfolio-evidence/, `${tc.name}: portfolio panel must not render`)
    } finally {
      h.unmount()
    }
  }

  // Mid-conversation scope flip in Auto mode without HTTP 409 must be rejected cleanly.
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'auto' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: portfolioFixture.request.message } })
    tree = h.render()
    h.queue({ status: 200, data: { scope: 'portfolio', ...portfolioFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: 'Switch silently' } })
    tree = h.render()
    h.queue({
      status: 200,
      data: {
        scope: 'risk',
        ...riskFixture.response,
        conversation_id: portfolioFixture.response.conversation_id,
      },
    })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const html = h.html(h.render())
    assert.match(html, /role="alert"/)
    assert.doesNotMatch(html, /portfolio-risk/)
  } finally {
    h.unmount()
  }
})

test('portfolio snapshot refresh strips risk_report and leaving risk clears stale policyRevision', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    // Switch to portfolio and refresh where server returns a PortfolioRiskEnvelope with risk_report.
    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'portfolio' } })
    tree = h.render()

    h.queue({
      status: 200,
      data: {
        ...portfolioFixture.response.portfolio_snapshot,
        risk_report: riskFixture.response.risk_snapshot.risk_report,
        risk_inputs: { stale: true },
      },
    })
    await findButton(tree, 'Refresh snapshot').props.onClick()
    await settle()

    tree = h.render()
    const evidenceNode = treeNodes(tree).find(
      n => typeof n.type === 'function' && n.props && 'snapshot' in n.props && 'positions' in (n.props.snapshot?.sections || {})
    )
    assert.ok(evidenceNode, 'Expected PortfolioEvidence element')
    assert.equal('risk_report' in evidenceNode.props.snapshot, false)
    assert.equal('risk_inputs' in evidenceNode.props.snapshot, false)

    // Switch to explicit risk, bump policyRevision via PortfolioRiskSettings.onRevision, then leave risk -> auto.
    findScopeSelect(h.render()).props.onChange({ target: { value: 'risk' } })
    tree = h.render()
    const riskSettingsNode = treeNodes(tree).find(n => typeof n.type === 'function' && typeof n.props?.onRevision === 'function')
    assert.ok(riskSettingsNode, 'Expected PortfolioRiskSettings element')
    riskSettingsNode.props.onRevision(7)
    await settle()

    // New chat within explicit risk must preserve policyRevision (PortfolioRiskSettings remains mounted).
    findTextarea(h.render()).props.onChange({ target: { value: riskFixture.request.message } })
    tree = h.render()
    h.queue({ status: 200, data: riskFixture.response })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()
    findButton(h.render(), 'New chat').props.onClick()
    await settle()
    findTextarea(h.render()).props.onChange({ target: { value: riskFixture.request.message } })
    tree = h.render()
    h.queue({ status: 200, data: riskFixture.response })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()
    assert.match(h.html(h.render()), /saved revision 7/)

    // Leaving explicit risk -> auto must clear stale policyRevision 7.
    findScopeSelect(h.render()).props.onChange({ target: { value: 'auto' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: riskFixture.request.message } })
    tree = h.render()
    h.queue({ status: 200, data: { scope: 'risk', ...riskFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    tree = h.render()
    assert.doesNotMatch(h.html(tree), /saved revision 7/)

    // Set policyRevision inside Auto (resolvedScope === 'risk'), click New chat, and re-submit.
    const autoRiskSettings = treeNodes(tree).find(n => typeof n.type === 'function' && typeof n.props?.onRevision === 'function')
    assert.ok(autoRiskSettings)
    autoRiskSettings.props.onRevision(9)
    await settle()

    findButton(h.render(), 'New chat').props.onClick()
    await settle()
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: riskFixture.request.message } })
    tree = h.render()
    h.queue({ status: 200, data: { scope: 'risk', ...riskFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    assert.doesNotMatch(h.html(h.render()), /saved revision 9/)
  } finally {
    h.unmount()
  }
})

test('changeContext preserves draft question, cleared Underlying disables chain Send, and Auto omits empty context', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    // Changing Underlying/Exchange preserves typed question draft.
    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'auto' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: 'Check my portfolio' } })
    tree = h.render()
    findInputByLabel(tree, 'Underlying').props.onChange({ target: { value: '' } })
    tree = h.render()
    assert.equal(findTextarea(tree).props.value, 'Check my portfolio')

    // In Auto mode with blank Underlying, Send stays enabled and unified-chat omits context.
    assert.equal(findButton(tree, 'Send question').props.disabled, false)
    h.queue({ status: 200, data: { scope: 'portfolio', ...portfolioFixture.response } })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    const autoCall = h.requests.filter(r => r.url === '/api/options-agent/unified-chat').at(-1)
    assert.equal('context' in autoCall.body, false)

    // In explicit chain mode with blank Underlying, Send is disabled to prevent HTTP 422.
    findScopeSelect(h.render()).props.onChange({ target: { value: 'chain' } })
    tree = h.render()
    findInputByLabel(tree, 'Underlying').props.onChange({ target: { value: '   ' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: 'Analyze NIFTY strikes' } })
    tree = h.render()
    assert.equal(findButton(tree, 'Send question').props.disabled, true)
  } finally {
    h.unmount()
  }
})

test('error alert does not wrap message in <p> so .error contrast is preserved', async () => {
  const h = createHarness()
  try {
    h.queue(readyStatus())
    h.render()
    await settle()

    let tree = h.render()
    findScopeSelect(tree).props.onChange({ target: { value: 'auto' } })
    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: chainFixture.request.message } })
    tree = h.render()
    h.queue({
      status: 200,
      data: { scope: 'chain', ...chainFixture.response, conversation_id: scopeChangeFixture.request.conversation_id },
    })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    tree = h.render()
    findTextarea(tree).props.onChange({ target: { value: scopeChangeFixture.request.message } })
    tree = h.render()
    h.queue({ status: scopeChangeFixture.status_code, data: scopeChangeFixture.response })
    await findForm(tree).props.onSubmit({ preventDefault() {} })
    await settle()

    tree = h.render()
    const alert = treeNodes(tree).find(n => n.props?.role === 'alert')
    assert.ok(alert)
    assert.equal(treeNodes(alert).some(n => n.type === 'p'), false)
    assert.ok(findButton(alert, 'New chat'))
  } finally {
    h.unmount()
  }
})
