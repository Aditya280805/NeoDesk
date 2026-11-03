import asyncio
import json
from unittest.mock import Mock
import pytest
from app.terminal.options_mcp import OptionsMCP
from app.terminal.options_report_context import bounded_report
from test_options_agent import app, client
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

def seed(app,kind,owner=1):
    id=str(uuid4())
    payload={'evidence_ids':['exact-evidence'], 'price':'123.456', 'observed_at':'2026-01-01T00:00:00Z'}
    if kind!='alert':payload['report_id']=id
    table={'strategy':'options_platform_artifacts','scan':'platform_scan_reports','alert':'platform_alert','backtest':'options_backtest_reports'}[kind]
    with app.state.store.connect() as db:
        if kind=='strategy':db.execute(f'INSERT INTO {table} VALUES(?,?,?,?,?)',('analysis',id,owner,'2026-01-01',json.dumps(payload)))
        elif kind=='alert':db.execute(f'INSERT INTO {table} VALUES(?,?,?,?,?,?,?,?,?)',(id,owner,1,id,'breach',json.dumps(payload),1,None,None))
        else:db.execute(f'INSERT INTO {table} VALUES(?,?,?)',(id,owner,json.dumps(payload)))
    return id

@pytest.mark.parametrize('kind',['strategy','scan','alert','backtest'])
def test_authenticated_explain_and_immutable_owner_history(client,app,monkeypatch,kind):
    from app.terminal import options_agent as module
    id=seed(app,kind)
    def build(config,snapshot,tools,*,scope):
        assert scope.allowed_tool==f'get_{kind}_report'
        assert scope.stored_context=={'scope':kind,'report_id':id}
        return SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content={'answer':'Historical observation age is 305 days; theoretical analysis is not recommendation eligibility.', 'report_ids':[id],'evidence_ids':['exact-evidence']})))
    monkeypatch.setattr(module,'build_agent',build)
    response=client.post('/api/options-platform/explain',json={'report_kind':kind,'report_id':id,'message':'Explain'})
    assert response.status_code==200,response.text
    data=response.json()
    assert data['report_ids']==[id] and data['evidence_ids']==['exact-evidence']
    history=app.state.options_agent.history(1,data['conversation_id'])
    assert history['turns'][0]['report']['report_id']==id
    app.state.market.call.assert_not_called()
    other=seed(app,kind,owner=999)
    assert client.post('/api/options-platform/explain',json={'report_kind':kind,'report_id':other,'message':'Explain'}).status_code==404
    assert client.post('/api/options-platform/explain',json={'report_kind':kind,'report_id':id,'message':'Explain','user_id':999}).status_code==422
    different=seed(app,kind)
    assert client.post('/api/options-platform/explain',json={'report_kind':kind,'report_id':different,'message':'Explain','conversation_id':data['conversation_id']}).status_code==409

def test_citation_failure_never_persists(client,app,monkeypatch):
    from app.terminal import options_agent as module
    id=seed(app,'scan')
    monkeypatch.setattr(module,'build_agent',lambda *a,**kw:SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content={'answer':'Invented', 'report_ids':[id],'evidence_ids':['wrong']}))))
    response=client.post('/api/options-platform/explain',json={'report_kind':'scan','report_id':id,'message':'Explain'})
    assert response.status_code==503
    with app.state.store.connect() as db:
        assert db.execute('SELECT count(*) FROM option_chat_turns').fetchone()[0]==0

def test_missing_report_does_not_invoke_model(client,app):
    from app.terminal import options_agent as module
    assert client.post('/api/options-platform/explain',json={'report_kind':'scan','report_id':str(uuid4()),'message':'Explain'}).status_code==404
    module.build_agent.assert_not_called()

def test_cancelled_explanation_has_no_successful_history(client,app,monkeypatch):
    from app.terminal import options_agent as module
    from app.terminal.agent_scope import ReportChatRequest
    id=seed(app,'scan')
    async def cancel(*args):raise asyncio.CancelledError()
    monkeypatch.setattr(module,'build_agent',lambda *a,**kw:SimpleNamespace(arun=cancel))
    async def run():
        with pytest.raises(asyncio.CancelledError):
            await app.state.options_agent.explain_report(1,ReportChatRequest(report_kind='scan',report_id=id,message='Explain'))
    # Use the app event loop hosting its private listener.
    client.portal.call(run)
    with app.state.store.connect() as db:
        assert db.execute('SELECT count(*) FROM option_chat_turns').fetchone()[0]==0

def test_unified_explicit_selection_bypasses_model_router(monkeypatch):
    from app.terminal import unified_chat as mod
    id=uuid4()
    service=SimpleNamespace(explain_report=AsyncMock(return_value={'answer':'Saved'}))
    router=AsyncMock(side_effect=AssertionError('Must not model-route report'))
    monkeypatch.setattr(mod,'route_question',router)
    result=asyncio.run(mod.dispatch_unified(service,8,mod.UnifiedChatRequest(message='Explain',report_kind='scan',report_id=id)))
    assert result['scope']=='scan'
    router.assert_not_called()

def test_mcp_rejects_selected_kind_mismatch():
    async def run():
        runtime=OptionsMCP(Mock(),port=0)
        async with runtime.lifespan():
            with pytest.raises(ValueError):
                async with runtime.connection(7,None,'run',scope='scan',selected_report={'report_kind':'backtest'}):pass
    asyncio.run(run())

@pytest.mark.parametrize('kind',['strategy','scan','alert','backtest'])
def test_report_private_protocol(kind):
    async def run():
        broker=Mock()
        runtime=OptionsMCP(broker,port=0)
        selected={'report_kind':kind,'report_id':'selected','evidence_ids':['ev'], 'report':{'price':'123.456'}}
        async with runtime.lifespan():
            async with runtime.connection(7,None,'run',scope=kind,selected_report=selected) as c:
                name=f'get_{kind}_report'
                assert list(c.tools.functions)==[name]
                selected['report']['price']='changed'
                first=await c._snapshot(name)
                assert first['report']['price']=='123.456'
                assert await c._snapshot(name)==first
                for args in ({'user_id':8},{'report_id':'other'}):
                    r=await c.tools.session.call_tool(name,args,raise_on_error=False)
                    assert r.is_error
                r=await c.tools.session.call_tool('get_option_snapshot',{},raise_on_error=False)
                assert r.is_error
                assert await c._snapshot(name)==first
                with pytest.raises(Exception):await c._snapshot(name)
                runtime.capabilities[c.token].expires=0
                with pytest.raises(Exception):await c._snapshot(name)
        broker.fetch.assert_not_called()
    asyncio.run(run())

def test_bounded_summary_preserves_whole_values():
    source={'report_kind':'scan','report_id':'saved','evidence_ids':['e'], 'report':{'rows':[{'price':'123.456','note':'x'*1000} for _ in range(100)]}}
    result=bounded_report(source)
    assert len(json.dumps(result).encode())<48000
    assert result['full_report_reference']=={'report_kind':'scan','report_id':'saved'}
    assert result['omitted_counts']
    assert '123.45' not in json.dumps(result).replace('123.456','')

def test_initial_selection_admitted_and_cancel_retains_capacity(client,app,monkeypatch):
    from app.terminal import options_agent as module
    from app.terminal.agent_scope import ReportChatRequest
    from fastapi import HTTPException
    from threading import Event
    entered,release=Event(),Event()
    original=module.load_report
    id=seed(app,'scan')
    calls=[]
    def blocked(*args):
        calls.append(args)
        entered.set()
        release.wait(3)
        return original(*args)
    monkeypatch.setattr(module,'load_report',blocked)
    async def run():
        service=app.state.options_agent
        body=ReportChatRequest(report_kind='scan',report_id=id,message='Explain')
        task=asyncio.create_task(service.explain_report(1,body))
        try:
            assert await asyncio.to_thread(entered.wait,1)
            assert 1 in service.active
            with pytest.raises(HTTPException) as error:
                await service.explain_report(1,body)
            assert error.value.status_code==409
            assert len(calls)==1
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            assert 1 in service.active
            with pytest.raises(HTTPException) as error:
                await service.explain_report(1,body)
            assert error.value.status_code==409
            module.build_agent.assert_not_called()
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            workers=set(service.workers.get(1,()))
            if workers:await asyncio.gather(*workers,return_exceptions=True)
            await asyncio.sleep(0)
        assert 1 not in service.active
    client.portal.call(run)

def test_initial_selection_uses_overall_deadline(client,app,monkeypatch):
    from app.terminal import options_agent as module
    from app.terminal.agent_scope import ReportChatRequest
    from fastapi import HTTPException
    from threading import Event
    entered,release=Event(),Event()
    original=module.load_report
    id=seed(app,'scan')
    def blocked(*args):
        entered.set();release.wait(3)
        return original(*args)
    monkeypatch.setattr(module,'load_report',blocked)
    service=app.state.options_agent
    monkeypatch.setattr(service,'deadline_seconds',0.05)
    async def run():
        try:
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(service.explain_report(1,ReportChatRequest(report_kind='scan',report_id=id,message='Explain')),0.5)
            assert error.value.status_code==504
            assert entered.is_set() and 1 in service.active
            module.build_agent.assert_not_called()
        finally:
            release.set()
            workers=set(service.workers.get(1,()))
            if workers:await asyncio.gather(*workers,return_exceptions=True)
    client.portal.call(run)

@pytest.mark.parametrize('failed_connection',[2,3])
def test_hydration_storage_failure_sanitized_at_every_read(failed_connection):
    import sqlite3
    from contextlib import contextmanager
    from app.terminal.options_report_context import load_report
    from fastapi import HTTPException
    calls=[]
    class Store:
        @contextmanager
        def connect(self):
            calls.append(1)
            if len(calls)==failed_connection:raise sqlite3.OperationalError('private database provider detail')
            db=Mock()
            db.execute.return_value.fetchone.return_value=(json.dumps({'evidence_ids':['exact']}),)
            yield db
    with pytest.raises(HTTPException) as error:
        load_report(Store(),1,'scan',uuid4())
    assert error.value.status_code==503
    assert 'private' not in error.value.detail
