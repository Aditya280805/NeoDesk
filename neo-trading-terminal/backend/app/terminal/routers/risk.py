
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from app.terminal.risk import RiskLimits

risk_router = APIRouter()

class KillSwitchRequest(BaseModel):
    reason: str = Field(default='Stopped from your dashboard',min_length=1,max_length=300)

def context(request):
    user=getattr(request.state,'user',None)
    uid=user['id'] if user else 1
    return request.app.state.risk_manager.for_user(uid),uid

@risk_router.get('/api/risk/status')
def get_risk_status(request: Request):
    manager,_=context(request)
    return manager.get_status()

@risk_router.post('/api/risk/kill-switch')
def trigger_kill_switch(request: Request, body: KillSwitchRequest | None=None):
    manager,uid=context(request)
    reason=(body or KillSwitchRequest()).reason
    manager.trigger_kill_switch(reason)
    request.app.state.store.audit(uid,'risk_kill_switch',f'Kill switch triggered: {reason}')
    return manager.get_status()

@risk_router.post('/api/risk/reset-kill-switch')
def reset_kill_switch(request: Request):
    manager,uid=context(request)
    manager.reset_kill_switch()
    request.app.state.store.audit(uid,'risk_kill_switch','Kill switch reset')
    return manager.get_status()

@risk_router.put('/api/risk/limits')
def update_risk_limits(request: Request, limits: RiskLimits):
    manager,uid=context(request)
    manager.limits = limits
    manager.save()
    request.app.state.store.audit(uid,'risk_limits_updated','Risk limits updated')
    return manager.get_status()
