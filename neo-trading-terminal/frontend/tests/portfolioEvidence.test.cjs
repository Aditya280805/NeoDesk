const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')
const moduleTarget = { exports: {} }
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/lib/portfolioEvidence.ts'), 'utf8')
// A VM-local guard proves regressions cannot attempt oversized allocations, even pre-fix.
const allocationGuard = `const originalRepeat = String.prototype.repeat; String.prototype.repeat = function(count) { if (count > 4096) throw new Error('oversized repeat attempted'); return originalRepeat.call(this, count) };`
vm.runInNewContext(allocationGuard + ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,{module:moduleTarget,exports:moduleTarget.exports})
const {formatDecimal} = moduleTarget.exports
for (const [input, expected] of [[null,'Unavailable'],['0','0'],['0.10','0.10'],['-12.30','-12.30'],['123456789012345678901234567890.12','123456789012345678901234567890.12']]) {
  test(`exact decimal ${input}`, () => assert.equal(formatDecimal(input),expected))
}
test('requested precision rounds using strings',()=>assert.equal(formatDecimal('999999999999999999.995',2),'1000000000000000000.00'))
for (const [input, expected] of [['1E-7','0.0000001'],['1E+30','1000000000000000000000000000000'],['-1.230E+3','-1230'],['+1.20e-2','0.0120'],['1.20E+0','1.20'],['0E+8','0'],['-0E-3','-0.000']]) {
  test(`exponent decimal ${input}`, () => assert.equal(formatDecimal(input), expected))
}
test('exponent value rounds without floating point',()=>assert.equal(formatDecimal('9.99999999999999999995E+18',1),'10000000000000000000.0'))

for (const input of ['1E+1000000000', '-1E-1000000000', '1E+9007199254740993', '1E-' + '9'.repeat(400)]) {
  test(`oversized exponent retained ${input.slice(0, 32)}`, () => {
    assert.equal(formatDecimal(input), input)
    assert.equal(formatDecimal(input, 2), input)
  })
}
