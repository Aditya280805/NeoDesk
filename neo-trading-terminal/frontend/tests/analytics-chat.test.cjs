const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
const ts = require('typescript')

function harness(api) {
  let cursor = 0
  const state = []
  const listeners = new Map()
  let effectStarted = false
  const hooks = {
    useEffect(effect) { if (!effectStarted) { effectStarted = true; effect() } },
    useState(initial) {
      const id = cursor++
      if (!(id in state)) state[id] = initial
      return [state[id], value => { state[id] = value }]
    },
    useRef(initial) {
      const id = cursor++
      if (!(id in state)) state[id] = { current: initial }
      return state[id]
    },
  }
  const source = fs.readFileSync(path.join(__dirname, '../src/components/AnalyticsChat.tsx'), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText
  const mod = { exports: {} }
  vm.runInNewContext(`(function(require,module,exports){${compiled}\n})`, { crypto: { randomUUID: () => 'action-fixed' }, window: {
    addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name),
  } })(
    name => name === 'react' ? hooks : name === '@/lib/api' ? { api, failure: error => error.message } : require(name), mod, mod.exports)
  const render = () => { cursor = 0; return mod.exports.default({ context: { underlying: 'NIFTY', exchange: 'nse_fo', expiry: null } }) }
  render.expire = () => listeners.get('neodesk:session-expired')?.()
  return render
}

function nodes(tree, type) {
  const result = []
  function visit(value) {
    if (Array.isArray(value)) return value.forEach(visit)
    if (!value || typeof value !== 'object') return
    if (value.type === type) result.push(value)
    visit(value.props?.children)
  }
  visit(tree)
  return result
}
const settle = () => new Promise(resolve => setImmediate(resolve))

test('analytics continues with original question/import and retries the same action', async () => {
  const calls = []
  let fail = false
  const render = harness(async (url, method, body) => {
    calls.push(body)
    if (fail) throw new Error('Connection lost')
    return { scope: 'analytics', read_only: true, status: 'partial', stages: [], answer: 'Pending', continuation_id: 'saved-run' }
  })
  let tree = render()
  nodes(tree, 'input')[0].props.onChange({ target: { value: 'Explain history' } })
  nodes(tree, 'textarea')[0].props.onChange({ target: { value: '{"provenance":"original"}' } })
  nodes(render(), 'form')[0].props.onSubmit({ preventDefault() {} })
  await settle()
  tree = render()
  nodes(tree, 'input')[0].props.onChange({ target: { value: 'Changed draft' } })
  nodes(tree, 'textarea')[0].props.onChange({ target: { value: '{"provenance":"changed"}' } })
  fail = true
  nodes(render(), 'button').find(button => button.props.children === 'Continue pending sections').props.onClick()
  await settle()
  fail = false
  nodes(render(), 'button').find(button => button.props.children === 'Continue pending sections').props.onClick()
  await settle()
  assert.equal(calls.length, 3)
  assert.equal(calls[1].message, 'Explain history')
  assert.equal(calls[1].historical_input.provenance, 'original')
  assert.equal(calls[1].continuation_action_id, calls[2].continuation_action_id)
})

test('invalid import JSON blocks submission before the API call', async () => {
  let calls = 0
  const render = harness(async () => { calls++ })
  let tree = render()
  nodes(tree, 'input')[0].props.onChange({ target: { value: 'Explain' } })
  nodes(tree, 'textarea')[0].props.onChange({ target: { value: 'invalid json' } })
  nodes(render(), 'form')[0].props.onSubmit({ preventDefault() {} })
  await settle()
  assert.equal(calls, 0)
  assert.equal(nodes(render(), 'p').find(p => p.props.role === 'alert').props.children, 'Historical input must be valid JSON.')
})

test('session expiry clears private drafts and rejects a delayed analytics reply', async () => {
  let deliver
  const render = harness(() => new Promise(resolve => { deliver = resolve }))
  let tree = render()
  nodes(tree, 'input')[0].props.onChange({ target: { value: 'Private question' } })
  nodes(tree, 'textarea')[0].props.onChange({ target: { value: '{"provenance":"Private import"}' } })
  nodes(render(), 'form')[0].props.onSubmit({ preventDefault() {} })
  render.expire()
  deliver({ scope: 'analytics', read_only: true, status: 'completed', stages: [], answer: 'Private result', continuation_id: null })
  await settle()
  tree = render()
  assert.equal(nodes(tree, 'input')[0].props.value, '')
  assert.equal(nodes(tree, 'textarea')[0].props.value, '')
  assert.equal(nodes(tree, 'p').some(node => node.props.children === 'Private result'), false)
})
