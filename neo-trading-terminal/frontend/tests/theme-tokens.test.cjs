const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('dark theme tokens match Kotak Neo palette', () => {
  const css = fs.readFileSync(path.join(__dirname, '../src/styles/globals.css'), 'utf8')
  assert.match(css, /--bg:\s*#070b12/i, 'dark bg must match Kotak Neo deep navy')
  assert.match(css, /--panel:\s*#0e1624/i, 'dark panel must match Kotak Neo surface')
  assert.match(css, /--line:\s*#1d2c42/i, 'dark line must match Kotak Neo border')
  assert.match(css, /--green:\s*#00d09c/i, 'dark green must match Kotak Neo vibrant emerald')
  assert.match(css, /--red:\s*#ff4757/i, 'dark red must match Kotak Neo coral red')
})

test('market theme tokens match Kotak Neo palette', () => {
  const css = fs.readFileSync(path.join(__dirname, '../src/styles/market.css'), 'utf8')
  assert.match(css, /--market-surface:\s*#0e1624/i, 'market surface must match Kotak Neo surface')
  assert.match(css, /--market-soft:\s*#152033/i, 'market soft must match Kotak Neo soft')
  assert.match(css, /--market-line:\s*#1d2c42/i, 'market line must match Kotak Neo line')
  assert.match(css, /--market-text:\s*#f1f5f9/i, 'market text must match Kotak Neo text')
  assert.match(css, /--market-muted:\s*#7e90a8/i, 'market muted must match Kotak Neo muted')
  assert.match(css, /--market-blue:\s*#2563eb/i, 'market blue must match Kotak Neo blue')
})
