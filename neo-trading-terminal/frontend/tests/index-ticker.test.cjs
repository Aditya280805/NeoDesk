const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('IndexTickerStrip source defines index mapping and polling interval', () => {
  const filePath = path.join(__dirname, '../src/components/IndexTickerStrip.tsx')
  assert.ok(fs.existsSync(filePath), 'IndexTickerStrip.tsx must exist')
  const content = fs.readFileSync(filePath, 'utf8')
  assert.match(content, /NIFTY 50|SENSEX/i, 'IndexTickerStrip must target key Indian indices')
  assert.match(content, /setInterval/i, 'IndexTickerStrip must set polling interval')
  assert.match(content, /market\/quotes/i, 'IndexTickerStrip must poll market quotes')
})

test('IndexTickerStrip adheres to Kotak Neo dark navy theme tokens and styles', () => {
  const filePath = path.join(__dirname, '../src/components/IndexTickerStrip.tsx')
  assert.ok(fs.existsSync(filePath), 'IndexTickerStrip.tsx must exist')
  const content = fs.readFileSync(filePath, 'utf8')
  assert.match(content, /#0E1624/i, 'Must use Kotak Neo surface dark navy #0E1624')
  assert.match(content, /#1D2C42/i, 'Must use Kotak Neo line #1D2C42')
  assert.match(content, /live-tick/i, 'Must include live-tick class for tick pulse')
  assert.match(content, /overflow-x-auto/i, 'Must support horizontal scroll for responsiveness')
  assert.match(content, /\/instrument\/\?instrument=/i, 'Must route to instrument page on click')
})
