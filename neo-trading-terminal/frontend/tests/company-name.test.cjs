const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')
function names(){
  const module={exports:{}}
  const source=fs.readFileSync(require('node:path').join(__dirname,'../src/lib/instruments.ts'),'utf8')
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{module,exports:module.exports})
  return module.exports
}
test('company names are readable and financial abbreviations stay recognizable',()=>{
  const {companyName}=names()
  assert.equal(companyName({symbol:'HDFCBANK-EQ',name:'HDFC BANK LTD'}),'HDFC Bank')
  assert.equal(companyName({symbol:'20MICRONS',name:'20 MICRONS LTD.'}),'20 Microns')
  assert.equal(companyName({symbol:'ITC-EQ',name:'ITC LIMITED'}),'ITC')
  assert.equal(companyName({symbol:'NIFTY',name:'NIFTY',display_name:'Nifty 50'}),'Nifty 50')
})
test('a missing company name falls back to the symbol without inventing a company',()=>{
  assert.equal(names().companyName({symbol:'UNKNOWN-EQ',name:''}),'UNKNOWN')
})
