const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('MarketTable contains quick buy and sell action buttons', () => {
  const content = fs.readFileSync(path.join(__dirname, '../src/components/MarketTable.tsx'), 'utf8')
  assert.match(content, /openOrderDrawer/i, 'MarketTable must use openOrderDrawer')
  assert.match(content, /quick-buy|quick-btn/i, 'MarketTable must render quick action buttons')
  assert.match(content, /aria-label=.*Buy/i, 'Quick buy button must have accessible label')
  assert.match(content, /aria-label=.*Sell/i, 'Quick sell button must have accessible label')
})

test('market.css styles quick action buttons and compact row density', () => {
  const css = fs.readFileSync(path.join(__dirname, '../src/styles/market.css'), 'utf8')
  assert.match(css, /\.quick-buy/i, 'market.css must define quick-buy button style')
  assert.match(css, /\.quick-sell/i, 'market.css must define quick-sell button style')
})
