const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('Layout mounts IndexTickerStrip and OrderDrawer', () => {
  const content = fs.readFileSync(path.join(__dirname, '../src/components/Layout.tsx'), 'utf8')
  assert.match(content, /IndexTickerStrip/i, 'Layout must mount IndexTickerStrip')
  assert.match(content, /OrderDrawer/i, 'Layout must mount OrderDrawer')
})

test('Layout topbar and sidebar styling in globals.css support active trader layout', () => {
  const css = fs.readFileSync(path.join(__dirname, '../src/styles/globals.css'), 'utf8')
  assert.match(css, /ticker-bar|topbar/i, 'globals.css must style topbar layout')
  assert.match(css, /\.sidebar\s+nav\s+a\.selected/i, 'globals.css must style selected sidebar navigation')
})
