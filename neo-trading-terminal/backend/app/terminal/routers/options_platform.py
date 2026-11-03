"""Authenticated strategy selections, evidence and immutable baselines; no MCP mutations."""
from uuid import UUID
from fastapi import APIRouter,Request,HTTPException,Query
from .options_agent import get_user_id
from ..options_snapshot import OptionsContext
from ..options_readiness import get_data_capabilities
from ..options_strategy_contracts import StrategyRequest,BaselineRequest
from ..options_platform_store import PlatformStoreBusyError,PlatformConflictError
from ..options_platform_risk import PlatformRiskPolicy,MonitoringSettings,EquityImport,AssociationRequest
from ..options_lot_ledger import LotLedgerImport
import time
from ..options_scanner import ScanCriteria

options_platform_router=APIRouter(prefix='/api/options-platform')
from .options_history import history_router
options_platform_router.include_router(history_router)

from ..agent_scope import ReportChatRequest

@options_platform_router.post('/explain')
async def explain_report(request:Request,body:ReportChatRequest):
    owner=get_user_id(request)
    return await request.app.state.options_agent.explain_report(owner,body)

@options_platform_router.post('/scans')
def create_scan(request:Request,body:ScanCriteria):
    return _call(request.app.state.options_scanner_service.create,get_user_id(request),body)

@options_platform_router.get('/scans')
def list_scans(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return _call(request.app.state.options_scanner_service.jobs.list,get_user_id(request),limit=limit,offset=offset)

@options_platform_router.get('/scans/{scan_id}')
def get_scan(request:Request,scan_id:UUID):
    return _found(_call(request.app.state.options_scanner_service.jobs.get,get_user_id(request),scan_id))

@options_platform_router.post('/scans/{scan_id}/cancel')
def cancel_scan(request:Request,scan_id:UUID):
    return _found(_call(request.app.state.options_scanner_service.jobs.cancel,get_user_id(request),scan_id))


def _call(function,*args,**kwargs):
    try: return function(*args,**kwargs)
    except PlatformStoreBusyError: raise HTTPException(503,'Options storage is busy. Retry shortly.',headers={'Retry-After':'1'}) from None
    except PlatformConflictError: raise HTTPException(409,'Immutable artifact identity conflicts.') from None

def _found(value):
    if value is None: raise HTTPException(404,'Artifact not found.')
    return value

@options_platform_router.get('/capabilities')
def capabilities(request:Request):
    get_user_id(request);return get_data_capabilities()

@options_platform_router.post('/market-snapshot')
async def market_snapshot(request:Request,body:OptionsContext):
    owner=get_user_id(request)
    try: return await request.app.state.options_platform_service.market_snapshot(owner,body)
    except PlatformStoreBusyError: raise HTTPException(503,'Options storage is busy.',headers={'Retry-After':'1'}) from None
    except PlatformConflictError: raise HTTPException(409,'Immutable artifact identity conflicts.') from None

@options_platform_router.post('/analyses')
async def analyses(request:Request,body:StrategyRequest):
    owner=get_user_id(request)
    try: return await request.app.state.options_platform_service.analyze(owner,body)
    except PlatformStoreBusyError: raise HTTPException(503,'Options storage is busy.',headers={'Retry-After':'1'}) from None
    except PlatformConflictError: raise HTTPException(409,'Immutable artifact identity conflicts.') from None

@options_platform_router.get('/analyses')
def list_analyses(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return _call(request.app.state.options_platform_store.list_reports,get_user_id(request),'analysis',limit=limit,offset=offset)

@options_platform_router.get('/analyses/{analysis_id}')
def get_analysis(request:Request,analysis_id:UUID):
    return _found(_call(request.app.state.options_platform_store.get_report,get_user_id(request),'analysis',analysis_id))

@options_platform_router.post('/baselines')
def baseline(request:Request,body:BaselineRequest):
    owner=get_user_id(request);store=request.app.state.options_platform_store
    _found(_call(store.get_report,owner,'analysis',body.analysis_id))
    return _call(store.save_baseline,owner,body.analysis_id,body.name)

@options_platform_router.get('/baselines')
def list_baselines(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return _call(request.app.state.options_platform_store.list_baselines,get_user_id(request),limit=limit,offset=offset)

@options_platform_router.get('/baselines/{baseline_id}')
def get_baseline(request:Request,baseline_id:UUID):
    return _found(_call(request.app.state.options_platform_store.get_baseline,get_user_id(request),baseline_id))

@options_platform_router.get('/risk-policy')
def get_platform_policy(request:Request):
    return _call(request.app.state.options_platform_store.get_risk_policy,get_user_id(request))

@options_platform_router.put('/risk-policy')
def put_platform_policy(request:Request,body:PlatformRiskPolicy):
    return _call(request.app.state.options_platform_store.put_risk_policy,get_user_id(request),body)

@options_platform_router.get('/monitoring')
def get_monitoring(request:Request):
    return _call(request.app.state.options_platform_store.get_monitoring,get_user_id(request))

@options_platform_router.put('/monitoring')
def put_monitoring(request:Request,body:MonitoringSettings):
    return _call(request.app.state.options_platform_store.put_monitoring,get_user_id(request),body,now=time.time())

@options_platform_router.get('/alerts')
def list_alerts(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return _call(request.app.state.options_platform_store.list_alerts,get_user_id(request),limit=limit,offset=offset)

@options_platform_router.post('/alerts/{alert_id}/read')
def read_alert(request:Request,alert_id:UUID):
    return _found(_call(request.app.state.options_platform_store.mark_alert,get_user_id(request),alert_id,'read',now=time.time()))

@options_platform_router.post('/alerts/{alert_id}/acknowledge')
def acknowledge_alert(request:Request,alert_id:UUID):
    return _found(_call(request.app.state.options_platform_store.mark_alert,get_user_id(request),alert_id,'acknowledge',now=time.time()))

@options_platform_router.post('/equity-imports')
def import_equity(request:Request,body:EquityImport):
    return _call(request.app.state.options_platform_store.import_equity,get_user_id(request),body,now=time.time())

@options_platform_router.get('/equity-imports')
def list_equity(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return _call(request.app.state.options_platform_store.list_private_records,get_user_id(request),'equity',limit=limit,offset=offset)

@options_platform_router.post('/lot-ledger-imports')
def import_lot_ledger(request:Request,body:LotLedgerImport):
    return _call(request.app.state.options_platform_store.import_lot_ledger,get_user_id(request),body,now=time.time())

@options_platform_router.get('/lot-ledger-imports')
def list_lot_ledgers(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return _call(request.app.state.options_platform_store.list_private_records,get_user_id(request),'lot_ledger',limit=limit,offset=offset)

@options_platform_router.post('/association-evidence')
async def acquire_association_evidence(request:Request):
    owner=get_user_id(request)
    try: return await request.app.state.options_monitoring_service.acquire_association_evidence(owner)
    except PlatformStoreBusyError: raise HTTPException(503,'Options storage is busy.',headers={'Retry-After':'1'}) from None
    except HTTPException: raise
    except Exception: raise HTTPException(503,'Association evidence unavailable. A valid broker session is required.') from None

@options_platform_router.get('/association-evidence')
def association_evidence(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return _call(request.app.state.options_platform_store.list_private_records,get_user_id(request),'portfolio',limit=limit,offset=offset)

@options_platform_router.post('/baselines/{baseline_id}/associations')
def associate_baseline(request:Request,baseline_id:UUID,body:AssociationRequest):
    owner=get_user_id(request)
    try: return _call(request.app.state.options_monitoring_service.associate,owner,baseline_id,body)
    except KeyError: raise HTTPException(404,'Baseline not found.') from None
    except ValueError: raise HTTPException(422,'Exact owned server evidence with compatible verified quantities and fills is required.') from None

@options_platform_router.get('/baselines/{baseline_id}/associations')
def association_history(request:Request,baseline_id:UUID,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    owner=get_user_id(request);store=request.app.state.options_platform_store
    _found(_call(store.get_baseline,owner,baseline_id))
    # Filter in SQL before pagination, so unrelated baselines do not hide history.
    return _call(store.list_associations,owner,baseline_id,limit=limit,offset=offset)

@options_platform_router.get('/risk-reports')
def risk_reports(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return _call(request.app.state.options_platform_store.list_private_records,get_user_id(request),'risk',limit=limit,offset=offset)
