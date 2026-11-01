const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

test('OrderDrawer component and store integration exists', () => {
  const storeContent = fs.readFileSync(path.join(__dirname, '../src/stores/marketStore.ts'), 'utf8')
  assert.match(storeContent, /orderDrawer/i, 'marketStore must include orderDrawer state')
  assert.match(storeContent, /openOrderDrawer/i, 'marketStore must include openOrderDrawer action')
  assert.match(storeContent, /closeOrderDrawer/i, 'marketStore must include closeOrderDrawer action')
  
  const drawerPath = path.join(__dirname, '../src/components/OrderDrawer.tsx')
  assert.ok(fs.existsSync(drawerPath), 'OrderDrawer.tsx must exist')
  const drawerContent = fs.readFileSync(drawerPath, 'utf8')
  assert.match(drawerContent, /TradeTicket/i, 'OrderDrawer must embed TradeTicket')
  assert.match(drawerContent, /closeOrderDrawer/i, 'OrderDrawer must use closeOrderDrawer')
  assert.match(drawerContent, /Escape/i, 'OrderDrawer must listen for Escape key')
})

test('OrderDrawer handles body overflow lock and backdrop dismissal', () => {
  const drawerPath = path.join(__dirname, '../src/components/OrderDrawer.tsx')
  assert.ok(fs.existsSync(drawerPath), 'OrderDrawer.tsx must exist')
  const drawerContent = fs.readFileSync(drawerPath, 'utf8')
  assert.match(drawerContent, /document\.body\.style\.overflow/i, 'OrderDrawer must manage document.body.style.overflow')
  assert.match(drawerContent, /useQuotes/i, 'OrderDrawer must query quotes with useQuotes')
  assert.match(drawerContent, /#0E1624|#070B12/i, 'OrderDrawer must use Kotak Neo theme dark background tokens')
})
