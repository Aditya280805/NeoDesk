// Isolated synthetic browser verification. Never connects to broker/model APIs.
const { chromium } = require('C:/Users/Aditya Bose/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
const http = require('node:http'), fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const root = path.resolve(__dirname, '../out')

;(async () => {
  const server = http.createServer((req, res) => {
    let file = path.resolve(root, '.' + decodeURIComponent(new URL(req.url, 'http://localhost').pathname))
    if (!file.startsWith(root + path.sep)) { res.writeHead(404); return res.end() }
    if (!path.extname(file)) file = path.join(file, 'index.html')
    try {
      res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html')
      res.end(fs.readFileSync(file))
    } catch { res.writeHead(404); res.end() }
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = `http://127.0.0.1:${server.address().port}`
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } })
  const page = await context.newPage(), errors = [], requests = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort())
  const now = new Date().toISOString()
  const proposal = { proposal_id: '11111111-1111-4111-8111-111111111111', template: 'bull_call_spread', legs: [
    { side: 'BUY', contract_id: 'synthetic-call-buy', quantity: 25 }, { side: 'SELL', contract_id: 'synthetic-call-sell', quantity: 25 },
  ] }
  const stage = (role, interpretation) => ({ role, status: 'completed', interpretation, claims: [], evidence: {
    synthetic: { status: 'PARTIAL', source_refs: ['synthetic-browser-only'], observed_at: now,
      metrics: { risk_verdict: 'CANNOT_ASSESS' }, unavailable_reasons: { margin: 'synthetic fixture: margin unavailable' } },
  } })
  await page.routeWebSocket('**/*', () => {})
  await page.route('**/api/**', async route => {
    const p = new URL(route.request().url()).pathname
    if (p === '/api/session') return route.fulfill({ json: { authenticated: true, user: { id: 999, email: 'fixture@example.invalid', display_name: 'Synthetic fixture' } } })
    if (p === '/api/status') return route.fulfill({ json: { market_data_source: 'fixture', broker_authenticated: false, live_trading_enabled: false, catalogue: { total: 0, counts: [] } } })
    if (p === '/api/options-agent/status') return route.fulfill({ json: { configured: true, model_configured: true, mcp_ready: true, read_only: true, analytics_tools_enabled: true, analytics_composite_enabled: true } })
    if (p === '/api/options-agent/unified-chat') {
      const body = route.request().postDataJSON(); requests.push(body)
      const completed = Boolean(body.continuation_id)
      return route.fulfill({ json: { scope: 'analytics', read_only: true, status: completed ? 'completed' : 'partial', answer: 'Synthetic read-only evidence.',
        stages: [stage('options_trading_analysis', 'Synthetic options evidence with limited coverage.'), ...(completed ? [stage('portfolio_risk', 'Margin remains unavailable in this synthetic fixture.')] : [])],
        selected_proposal: proposal, continuation_id: completed ? null : '22222222-2222-4222-8222-222222222222',
        pending: completed ? [] : [{ role: 'portfolio_risk', tools: ['run_spot_vix_cvar_stress_matrix'] }] } })
    }
    return route.fulfill({ json: {} })
  })
  try {
    await page.goto(origin + '/options-chat/')
    const panel = page.getByRole('region', { name: 'Composite analytics' })
    await panel.getByRole('heading', { name: 'Composite analytics', exact: true }).waitFor()
    await panel.getByLabel('Analytics question', { exact: true }).fill('Analyze the synthetic scenario')
    await panel.getByText('Optional historical inputs', { exact: true }).click()
    const imported = { context: { underlying: 'NIFTY', exchange: 'nse_fo', expiry: null }, provenance: 'Synthetic browser fixture', licence: 'Testing only', observed_at: now, return_dates: [now], cash_flow_adjusted_returns: [.01] }
    await panel.getByLabel('Declared historical input JSON').fill(JSON.stringify(imported))
    await panel.getByRole('button', { name: 'Analyze', exact: true }).click()
    await panel.getByText('Status: partial', { exact: true }).waitFor()
    await panel.getByRole('heading', { name: 'Selected hypothetical proposal' }).waitFor()
    await panel.getByLabel('Analytics question', { exact: true }).fill('Edited draft must not change continuation')
    await panel.getByRole('button', { name: 'Continue pending sections' }).click()
    await panel.getByText('Status: completed', { exact: true }).waitFor()
    assert.equal(requests.length, 2)
    assert.equal(requests[1].message, requests[0].message)
    assert.deepEqual(requests[1].historical_input, requests[0].historical_input)
    assert.equal(requests[1].analytics_mode, true)
    await panel.getByText('Evidence, coverage and proposal candidates', { exact: true }).first().click()
    const directory = path.resolve(__dirname, '../../docs/superpowers/implementation/agents-v2/browser')
    fs.mkdirSync(directory, { recursive: true })
    await panel.screenshot({ path: path.join(directory, 'analytics-desktop.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.waitForTimeout(200)
    await panel.screenshot({ path: path.join(directory, 'analytics-mobile.png') })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    assert.equal(overflow, false, 'Mobile document must not overflow horizontally')
    assert.deepEqual(errors, [])
    console.log('PASS synthetic desktop/mobile analytics, proposal display, evidence expansion, continuation binding, clean page errors, no horizontal overflow')
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)) }
})().catch(error => { console.error(error); process.exitCode = 1 })
