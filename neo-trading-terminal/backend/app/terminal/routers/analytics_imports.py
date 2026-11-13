"""Private historical-input management; identifiers never authorize another owner."""
from uuid import UUID
from fastapi import APIRouter,Request,HTTPException
from ..analytics_inputs import AnalyticsInputStore
from ..analytics_store import AnalyticsStore

router=APIRouter(prefix='/imports')

def owned(request):
    user=getattr(request.state,'user',None)
    owner=user.get('id') if isinstance(user,dict) else None
    if type(owner) is not int or owner<=0: raise HTTPException(401,'Sign in to your individual account.')
    return owner,AnalyticsInputStore(AnalyticsStore(request.app.state.store.path))

@router.get('')
def list_imports(request:Request):
    owner,store=owned(request)
    return dict(items=store.list_owned(owner))

@router.delete('/{dataset_id}')
def delete_import(request:Request,dataset_id:UUID):
    owner,store=owned(request)
    if not store.delete_owned(owner,dataset_id): raise HTTPException(404,'Import unavailable.')
    return dict(deleted=True)
