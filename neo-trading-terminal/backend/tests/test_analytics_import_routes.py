from types import SimpleNamespace
from datetime import UTC,datetime
from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from app.terminal.routers.analytics_imports import router
from app.terminal.analytics_inputs import AnalyticsInputStore,HistoricalAnalyticsInput
from app.terminal.analytics_store import AnalyticsStore
from app.terminal.options_snapshot import OptionsContext

def test_import_routes_require_owner_and_reject_cross_account_delete(tmp_path):
    store=AnalyticsStore(tmp_path/'imports.sqlite3')
    imports=AnalyticsInputStore(store)
    saved=imports.save(7,HistoricalAnalyticsInput(context=OptionsContext(),provenance='owner',licence='owner',observed_at=datetime.now(UTC),ledger_csv='date,type,amount_paise\n2026-01-01,DEPOSIT,10'))
    app=FastAPI()
    app.state.store=store
    identity={'id':8}
    @app.middleware('http')
    async def auth(request:Request,call_next):
        request.state.user=identity.copy()
        return await call_next(request)
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/imports').json()=={'items':[]}
        assert client.delete('/imports/'+saved['dataset_id']).status_code==404
        identity['id']=7
        assert len(client.get('/imports').json()['items'])==1
        assert client.delete('/imports/'+saved['dataset_id']).json()=={'deleted':True}
        assert client.get('/imports').json()=={'items':[]}
        identity.clear()
        assert client.get('/imports').status_code==401
