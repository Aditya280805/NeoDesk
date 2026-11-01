const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('trading page and TradeTicket support square-off and product tabs', () => {
  const ticketContent = fs.readFileSync(path.join(__dirname, '../src/components/TradeTicket.tsx'), 'utf8')
  assert.match(ticketContent, /MIS|CNC|NRML/i, 'TradeTicket must display product tabs or indicators')
  
  const tradingContent = fs.readFileSync(path.join(__dirname, '../src/pages/trading.tsx'), 'utf8')
  assert.match(tradingContent, /Square off|square-off/i, 'trading page must render square off button')
  assert.match(tradingContent, /square-off-btn/i, 'trading page must include square-off-btn class')
  
  const brokerContent = fs.readFileSync(path.join(__dirname, '../src/components/BrokerPortfolio.tsx'), 'utf8')
  assert.match(brokerContent, /Square off|square-off/i, 'BrokerPortfolio must render square off button')
  assert.match(brokerContent, /square-off-btn/i, 'BrokerPortfolio must include square-off-btn class')
})

test('TradeTicket supports quantity stepper and initialQuantity prop', () => {
  const ticketContent = fs.readFileSync(path.join(__dirname, '../src/components/TradeTicket.tsx'), 'utf8')
  assert.match(ticketContent, /initialQuantity/i, 'TradeTicket must accept initialQuantity prop')
  assert.match(ticketContent, /\+1/i, 'TradeTicket must have +1 quantity stepper')
  assert.match(ticketContent, /\+5/i, 'TradeTicket must have +5 quantity stepper')
})

test('square-off flow passes inverse side and net quantity to TradeTicket', () => {
  const tradingContent = fs.readFileSync(path.join(__dirname, '../src/pages/trading.tsx'), 'utf8')
  assert.match(tradingContent, /initialSide/i, 'trading page must pass initialSide to TradeTicket')
  assert.match(tradingContent, /initialQuantity/i, 'trading page must pass initialQuantity to TradeTicket')
  
  const brokerContent = fs.readFileSync(path.join(__dirname, '../src/components/BrokerPortfolio.tsx'), 'utf8')
  assert.match(brokerContent, /initialSide/i, 'BrokerPortfolio must pass initialSide to TradeTicket')
  assert.match(brokerContent, /initialQuantity/i, 'BrokerPortfolio must pass initialQuantity to TradeTicket')
})
