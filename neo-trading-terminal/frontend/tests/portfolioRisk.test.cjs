const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript')
const m={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/portfolioRisk.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,{module:m,exports:m.exports});const r=m.exports
 test('unset and exact zero remain distinct',()=>{assert.equal(r.optionalDecimal(''),null);assert.equal(r.optionalDecimal('0'),'0');assert.equal(r.optionalDecimal('0.00000001'),'0.00000001');assert.throws(()=>r.optionalDecimal('1e2'))})
 test('disabled all and incomplete coverage never imply pass',()=>{assert.equal(r.reportLabel({summary:'cannot_assess',coverage:{disabled:4,passed:0,breached:0,cannot_assess:0}}),'Cannot assess · all checks disabled');assert.equal(r.reportLabel({summary:'cannot_assess',coverage:{disabled:0,passed:1,breached:0,cannot_assess:3}}),'Cannot assess')})
 test('reports retain evaluated revision and legacy absence',()=>{assert.equal(r.olderPolicy({policy_revision:1},2),true);assert.equal(r.olderPolicy(undefined,2),false)})
 test('conflict retains draft until explicit reload',()=>{const state={draft:{concentration_max_percent:'0'},revision:1};const next=r.policyConflict(state);assert.equal(next.draft,state.draft);assert.equal(next.conflict,true);assert.equal(next.revision,1)})
 test('request publication requires active scope and session generation',()=>{assert.equal(r.canPublish(2,3,true),false);assert.equal(r.canPublish(2,2,false),false);assert.equal(r.canPublish(2,2,true),true)})

function loadComponent(file, overrides={}) {
 const module={exports:{}}
 const output=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText
 vm.runInNewContext(output,{module,exports:module.exports,require:name=>overrides[name]??(name==='@/lib/portfolioRisk'?r:require(name)),...overrides.globals})
 return module.exports.default
}
function treeNodes(tree){if(!tree||typeof tree!=='object')return [];return [tree,...[tree.props?.children].flat(Infinity).flatMap(treeNodes)]}
function textOf(tree){if(Array.isArray(tree))return tree.map(textOf).join('');return typeof tree==='object'&&tree?textOf(tree.props?.children):String(tree??'')}
function settingsHarness() {
 const React=require('react'), slots=[],effects=[], events=new Map(), requests=[];let index=0, initialized=false, responseQueue=[]
 const hooks={...React,useState:initial=>{const slot=index++;if(!(slot in slots))slots[slot]=initial;return [slots[slot],next=>slots[slot]=typeof next==='function'?next(slots[slot]):next]},useRef:initial=>{const slot=index++;return slots[slot]??(slots[slot]={current:initial})},useEffect:fn=>{if(!initialized)effects.push(fn)}}
 const revisions=[],dispatched=[],cleanups=[]
 const Component=loadComponent('src/components/PortfolioRiskSettings.tsx',{react:hooks,'@/lib/api':{apiBase:()=>'',failure:e=>e.message},globals:{AbortSignal:{timeout:()=>undefined},Event,window:{addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:name=>events.delete(name),dispatchEvent:event=>{dispatched.push(event.type);events.get(event.type)?.()}},fetch:async(url,options)=>{requests.push({url,...options});const next=responseQueue.shift();return typeof next==='function'?next():next}}})
 const render=()=>{index=0;const tree=Component({onRevision:n=>revisions.push(n)});if(!initialized){initialized=true;effects.forEach(fn=>cleanups.push(fn()))}return tree}
 return {render,requests,revisions,dispatched,queue:(...responses)=>responseQueue.push(...responses),expire:()=>events.get('neodesk:session-expired')?.(),unmount:()=>cleanups.forEach(fn=>fn?.())}
}
const policyFixture=(revision=1)=>({policy:{schema_version:'portfolio-risk-policy.v1',revision,concentration_enabled:true,expiry_enabled:true,margin_enabled:true,loss_enabled:true,concentration_max_percent:'50',expiry_window_days:null,margin_max_percent:null,loss_max_amount:null,loss_basis:null,loss_period:null,max_observation_age_seconds:null},supported_inputs:{margin:false,loss:false}})
const response=(data,status=200)=>({ok:status<400,status,json:async()=>data})
const settle=()=>new Promise(resolve=>setImmediate(resolve))
const form=tree=>treeNodes(tree).find(n=>n.type==='form')
const limitInput=tree=>treeNodes(tree).find(n=>n.type==='input'&&n.props.value==='50')
const button=(tree,name)=>treeNodes(tree).find(n=>n.type==='button'&&textOf(n)===name)

test('policy component retains conflict draft, blocks another PUT, explicitly reloads revision',async()=>{
 const h=settingsHarness();h.queue(response(policyFixture()));h.render();await settle()
 limitInput(h.render()).props.onChange({target:{value:'0'}})
 h.queue(response({detail:'Conflict'},409));await form(h.render()).props.onSubmit({preventDefault(){}})
 let tree=h.render();assert.match(textOf(tree),/unsaved edits are retained/);assert.ok(treeNodes(tree).some(n=>n.type==='input'&&n.props.value==='0'));assert.equal(button(tree,'Save policy').props.disabled,true)
 const count=h.requests.length;await form(tree).props.onSubmit({preventDefault(){}});assert.equal(h.requests.length,count)
 h.queue(response(policyFixture(2)));await button(tree,'Reload latest policy for review').props.onClick();await settle()
 tree=h.render();assert.equal(button(tree,'Save policy').props.disabled,false);assert.match(textOf(tree),/Latest policy loaded. Review before saving/);assert.equal(limitInput(tree).props.value,'50');assert.deepEqual(h.revisions,[1,2])
})
test('invalid monetary draft stays visible and cannot submit a stale previous value',async()=>{
 const h=settingsHarness();h.queue(response(policyFixture()));h.render();await settle();limitInput(h.render()).props.onChange({target:{value:'1e2'}})
 let tree=h.render();assert.ok(treeNodes(tree).some(n=>n.type==='input'&&n.props.value==='1e2'));await form(tree).props.onSubmit({preventDefault(){}})
 assert.equal(h.requests.length,1);assert.match(textOf(h.render()),/Use a nonnegative decimal/)
})
test('policy save keeps decimal zero as a string and strips revision from settings',async()=>{
 const h=settingsHarness();h.queue(response(policyFixture()));h.render();await settle();limitInput(h.render()).props.onChange({target:{value:'0'}})
 h.queue(response({...policyFixture(2),policy:{...policyFixture(2).policy,concentration_max_percent:'0'}}));await form(h.render()).props.onSubmit({preventDefault(){}})
 const body=JSON.parse(h.requests[1].body);assert.equal(body.expected_revision,1);assert.equal(body.policy.concentration_max_percent,'0');assert.equal('revision' in body.policy,false);assert.match(textOf(h.render()),/Applies to the next eligible refresh/)
})
test('late policy load cannot republish after session expiry',async()=>{
 let resolve;const h=settingsHarness();h.queue(()=>new Promise(r=>resolve=r));h.render();h.expire();resolve(response(policyFixture(8)));await settle();assert.deepEqual(h.revisions,[]);assert.doesNotMatch(textOf(h.render()),/Saved revision 8/)
})
test('report component renders old revision, stale retained report, ratio strings and unsupported reasons',()=>{
 const Panel=loadComponent('src/components/PortfolioRiskPanel.tsx'), render=require('react-dom/server').renderToStaticMarkup, React=require('react')
 const report={policy_revision:1,summary:'cannot_assess',coverage:{passed:0,breached:0,cannot_assess:4,disabled:0},report_id:'immutable-report',calculation_version:'portfolio-risk.1',evaluated_at:'2026-10-30T00:00:00Z',findings:[{code:'margin',enabled:true,outcome:'cannot_assess',measured:'33.33333333',limit:'33.33333334',unit:'percent',numerator:'1.00000001',denominator:'3.00000003',affected_row_ids:['row-1'],reason_codes:['unsupported_basis']}],observation_times:{funds:{retrieval_started_at:'2026-10-30T00:00:00Z',retrieval_finished_at:'2026-10-30T00:00:01Z',source_timestamp:null}},limitations:[]}
 const html=render(React.createElement(Panel,{report,currentRevision:2,stale:true}));for(const pattern of [/older policy/,/Stale evidence/,/immutable-report/,/33.33333333/,/33.33333334/,/1.00000001/,/3.00000003/,/row-1/,/unsupported basis/,/source Unavailable/])assert.match(html,pattern)
 assert.match(render(React.createElement(Panel,{})),/No risk report in this historical evidence/)
})
test('settings render unsupported margin and account P&L capabilities without suggested limits',async()=>{
 const h=settingsHarness();h.queue(response(policyFixture()));h.render();await settle();const text=textOf(h.render());assert.match(text,/documented account margin inputs are unsupported/);assert.match(text,/account net P&L basis and period inputs are unsupported/);assert.match(text,/No recommended limits/)
})

test('delayed 401 after policy settings unmount cannot expire the current session',async()=>{
 let resolve;const h=settingsHarness();h.queue(()=>new Promise(r=>resolve=r));h.render();h.unmount();resolve(response({detail:'Old session'},401));await settle();assert.deepEqual(h.dispatched,[]);assert.deepEqual(h.revisions,[])
})
test('delayed 401 after session generation changes cannot expire a replacement session',async()=>{
 let resolve;const h=settingsHarness();h.queue(()=>new Promise(r=>resolve=r));h.render();h.expire();resolve(response({detail:'Old session'},401));await settle();assert.deepEqual(h.dispatched,[])
})
test('delayed policy PUT 401 cannot expire a replacement session',async()=>{
 let resolve;const h=settingsHarness();h.queue(response(policyFixture()));h.render();await settle();h.queue(()=>new Promise(r=>resolve=r));const saving=form(h.render()).props.onSubmit({preventDefault(){}});h.expire();resolve(response({detail:'Old session'},401));await saving;assert.deepEqual(h.dispatched,[]);assert.deepEqual(h.revisions,[1])
})
test('active policy 401 still expires the current session',async()=>{
 const h=settingsHarness();h.queue(response({detail:'Expired session'},401));h.render();await settle();assert.deepEqual(h.dispatched,['neodesk:session-expired'])
})
test('unmount never reactivates an expired reload generation',async()=>{
 let resolve;const h=settingsHarness();h.queue(response(policyFixture()));h.render();await settle();h.expire();h.queue(()=>new Promise(r=>resolve=r));button(h.render(),'Retry policy load').props.onClick();h.expire();h.unmount();resolve(response({detail:'Old reload'},401));await settle();assert.deepEqual(h.dispatched,[])
})
test('report component renders frozen specialist_api risk.json payload without portfolio sections',()=>{
 const fs=require('node:fs'),path=require('node:path'),React=require('react'),render=require('react-dom/server').renderToStaticMarkup
 const Panel=loadComponent('src/components/PortfolioRiskPanel.tsx')
 const fixture=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../backend/evals/fixtures/specialist_api/risk.json'),'utf8'))
 const report=fixture.response.risk_snapshot.risk_report
 const html=render(React.createElement(Panel,{report,currentRevision:0}))
 assert.match(html,new RegExp(report.report_id))
 assert.match(html,/portfolio-risk\.1/)
 assert.match(html,/cannot assess/i)
 assert.match(html,/limit not configured/i)
 assert.doesNotMatch(html,/portfolio-evidence/)
 assert.doesNotMatch(html,/Portfolio summaries/)
})
