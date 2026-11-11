from uuid import UUID
from app.terminal.agent_scope import PortfolioChatRequest, PortfolioSnapshotRequest

from fastapi import APIRouter, Request, HTTPException

from app.terminal.options_agent import ChatRequest, OptionsContext
from app.terminal.unified_chat import UnifiedChatRequest, dispatch_unified

def get_user_id(request):
    user = getattr(request.state, 'user', None)
    if not user or not user.get('id'):
        raise HTTPException(401, 'Sign in to your individual account to use options monitoring.')
    return user['id']


options_agent_router = APIRouter(prefix='/api/options-agent')


@options_agent_router.post('/unified-chat')
async def unified_chat(request: Request, body: UnifiedChatRequest):
    return await dispatch_unified(request.app.state.options_agent, get_user_id(request), body)


@options_agent_router.get('/status')
def status(request: Request):
    get_user_id(request)
    return request.app.state.options_agent.status()


@options_agent_router.post('/snapshot')
async def snapshot(request: Request, body: OptionsContext):
    return await request.app.state.options_agent.snapshot(get_user_id(request), body)


@options_agent_router.post('/chat')
async def chat(request: Request, body: ChatRequest):
    return await request.app.state.options_agent.chat(get_user_id(request), body)


@options_agent_router.get('/conversations/{conversation_id}')
def history(request: Request, conversation_id: UUID):
    return request.app.state.options_agent.history(get_user_id(request), conversation_id)


@options_agent_router.get('/runs/{run_id}')
def run_record(request: Request, run_id: UUID):
    return request.app.state.options_agent.run_record(get_user_id(request), run_id)


@options_agent_router.post('/portfolio/snapshot')
async def portfolio_snapshot(request: Request, body: PortfolioSnapshotRequest | None = None):
    return await request.app.state.options_agent.portfolio_snapshot(get_user_id(request))


@options_agent_router.post('/portfolio/chat')
async def portfolio_chat(request: Request, body: PortfolioChatRequest):
    return await request.app.state.options_agent.portfolio_chat(get_user_id(request), body)


@options_agent_router.post('/portfolio/risk/chat')
async def portfolio_risk_chat(request: Request, body: PortfolioChatRequest):
    return await request.app.state.options_agent.portfolio_risk_chat(get_user_id(request), body)


from app.terminal.portfolio_risk_contracts import RiskPolicyUpdate
from app.terminal.portfolio_risk_store import PolicyConflictError, RiskStoreBusyError


def _policy_response(policy):
    return {'policy': policy.model_dump(mode='json'), 'supported_inputs': {'margin': False, 'loss': False}}


@options_agent_router.get('/portfolio/risk-policy')
def risk_policy(request: Request):
    user_id = get_user_id(request)
    try:
        return _policy_response(request.app.state.portfolio_risk_store.get_policy(user_id))
    except RiskStoreBusyError:
        raise HTTPException(503, 'Risk storage is busy. Retry shortly.', headers={'Retry-After':'1'}) from None


@options_agent_router.put('/portfolio/risk-policy')
def update_risk_policy(request: Request, body: RiskPolicyUpdate):
    user_id = get_user_id(request)
    try:
        return _policy_response(request.app.state.portfolio_risk_store.update_policy(user_id, body))
    except PolicyConflictError:
        raise HTTPException(409, 'Risk policy changed. Reload before updating.') from None
    except RiskStoreBusyError:
        raise HTTPException(503, 'Risk storage is busy. Retry shortly.', headers={'Retry-After':'1'}) from None
