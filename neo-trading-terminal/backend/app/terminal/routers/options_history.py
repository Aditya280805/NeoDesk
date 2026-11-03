"""Authenticated bounded raw import payloads with sanitized validation errors."""
import base64
import json
from uuid import UUID
from fastapi import APIRouter,Request,HTTPException,Query
from starlette.concurrency import run_in_threadpool
from .options_agent import get_user_id
from ..options_history import parse_history, HistoryValidationError
from ..options_history_contracts import HistoricalImportBody, ImportDeclaration, BacktestRequest, MAX_BYTES
from ..options_platform_store import PlatformStoreBusyError,PlatformConflictError

history_router=APIRouter()

async def bounded_json(request,model,limit):
    chunks=[];length=0
    async for chunk in request.stream():
        length+=len(chunk)
        if length>limit:raise HTTPException(413,'Historical payload exceeds size limit.')
        chunks.append(chunk)
    try:return model.model_validate(json.loads(b''.join(chunks)))
    except Exception:raise HTTPException(422,'Historical request schema is invalid.') from None

def execute(function,*args,**kwargs):
    try:return function(*args,**kwargs)
    except HistoryValidationError as exc:raise HTTPException(422,dict(row=exc.row,code=exc.code,message=exc.message)) from None
    except KeyError:raise HTTPException(404,'Artifact not found.') from None
    except PlatformConflictError:raise HTTPException(409,'Heavy queue is full.') from None
    except PlatformStoreBusyError:raise HTTPException(503,'Options storage is busy.',headers={'Retry-After':'1'}) from None
    except ValueError:raise HTTPException(422,'Historical period or evidence is unsupported.') from None

def found(value):
    if value is None:raise HTTPException(404,'Artifact not found.')
    return value

@history_router.post('/historical-imports')
async def import_history(request:Request):
    owner=get_user_id(request)
    body=await bounded_json(request,HistoricalImportBody,MAX_BYTES*6+8192)
    try:payload=body.csv_text.encode('utf-8') if body.format=='csv' else base64.b64decode(body.parquet_base64,validate=True)
    except Exception:raise HTTPException(422,'Invalid historical payload encoding.') from None
    declaration=ImportDeclaration.model_validate(body.model_dump(exclude={'format','csv_text','parquet_base64'}))
    def save():
        parsed=parse_history(payload,body.format,declaration)
        return request.app.state.options_backtest_service.history.save(owner,parsed)
    return await run_in_threadpool(execute,save)

@history_router.get('/historical-imports')
def list_history(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return execute(request.app.state.options_backtest_service.history.list,get_user_id(request),limit=limit,offset=offset)

@history_router.get('/historical-imports/{dataset_id}')
def get_history(request:Request,dataset_id:UUID):
    return found(execute(request.app.state.options_backtest_service.history.get,get_user_id(request),dataset_id))

@history_router.post('/backtests')
async def create_backtest(request:Request):
    owner=get_user_id(request);body=await bounded_json(request,BacktestRequest,2*1024*1024)
    return await run_in_threadpool(execute,request.app.state.options_backtest_service.create,owner,body)

@history_router.get('/backtests')
def list_backtests(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
    return execute(request.app.state.options_backtest_service.list,get_user_id(request),limit=limit,offset=offset)

@history_router.get('/backtests/{backtest_id}')
def get_backtest(request:Request,backtest_id:UUID):
    return found(execute(request.app.state.options_backtest_service.get,get_user_id(request),backtest_id))

@history_router.post('/backtests/{backtest_id}/cancel')
def cancel_backtest(request:Request,backtest_id:UUID):
    return found(execute(request.app.state.options_backtest_service.cancel,get_user_id(request),backtest_id))
