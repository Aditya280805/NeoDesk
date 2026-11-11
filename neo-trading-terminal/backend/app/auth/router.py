"""FastAPI authentication routes for NeoDesk."""
import time
from threading import Lock
from typing import Dict, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status

from app.core.config import settings
from app.auth.models import TokenResponse, UserLogin, UserRegister, UserResponse, KotakLogin
from app.auth.service import authenticate_user, create_token, create_user
from app.auth.dependencies import get_current_user
from app.brokers.base_broker import BrokerError
from app.terminal.portfolio import snapshot

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

# Rate limit storage (IP -> list of timestamps)
_RATE_WINDOW_SECONDS = 60
_MAX_RATE_IPS = 4096
_register_attempts: Dict[str, List[float]] = {}
_login_attempts: Dict[str, List[float]] = {}
_rate_lock = Lock()


def _check_rate_limit(attempts: Dict[str, List[float]], ip: str, max_limit: int, action: str, lock: Lock = _rate_lock):
    now = time.time()
    cutoff = now - _RATE_WINDOW_SECONDS
    with lock:
        if len(attempts) > 1000:
            stale = [key for key, stamps in attempts.items() if not any(t > cutoff for t in stamps)]
            for key in stale:
                del attempts[key]
        recent = [t for t in attempts.get(ip, []) if t > cutoff]
        if len(recent) >= max_limit:
            attempts[ip] = recent
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many {action} attempts. Wait a minute before trying again.",
            )
        if not recent and ip in attempts:
            del attempts[ip]
        if ip not in attempts and len(attempts) >= _MAX_RATE_IPS:
            for key in list(attempts):
                active = [t for t in attempts[key] if t > cutoff]
                if active:
                    attempts[key] = active
                else:
                    del attempts[key]
            while len(attempts) >= _MAX_RATE_IPS:
                oldest_key = min(attempts, key=lambda k: max(attempts[k], default=0.0))
                del attempts[oldest_key]
        recent.append(now)
        attempts[ip] = recent


def _clear_rate_limits():
    """Helper for testing to reset rate limit counters."""
    with _rate_lock:
        _register_attempts.clear()
        _login_attempts.clear()


@auth_router.post('/kotak-login')
def kotak_login(body: KotakLogin, request: Request, response: Response, background_tasks: BackgroundTasks):
    _check_rate_limit(_login_attempts,request.client.host if request.client else 'unknown',5,'login')
    market,store=request.app.state.market,request.app.state.store
    try:
        user=market.sign_in(body.consumer_key.get_secret_value().strip(),body.ucc.upper(),body.mobile,
                            body.totp.get_secret_value(),body.mpin.get_secret_value())
    except BrokerError:
        raise HTTPException(401,'Kotak could not verify your login. Check your details and use a fresh TOTP.') from None
    sync_error=None
    try:
        snapshot(market,store,user['id'],force=True)
    except BrokerError:
        sync_error='Signed in. Portfolio sync is temporarily unavailable; use Refresh on your portfolio.'
    lock=request.app.state.catalogue_lock
    updated=store.metadata().get('updated_at')
    from datetime import datetime, UTC
    stale=not updated or (datetime.now(UTC)-datetime.fromisoformat(updated)).total_seconds()>86400
    if stale and lock.acquire(blocking=False):
        sync_by_user=getattr(request.app.state,'catalogue_sync_by_user',None)
        user_status={'running':True,'error':None}
        if isinstance(sync_by_user,dict):
            sync_by_user[user['id']]=user_status
        progress=request.app.state.catalogue_sync
        progress.update(running=True,error=None)
        def sync_catalogue():
            try:
                market.sync(user_id=user['id'])
            except Exception:
                err_msg='Catalogue sync is unavailable. Use Retry in Connections.'
                user_status['error']=err_msg
                progress['error']=err_msg
            finally:
                user_status['running']=False
                progress['running']=False
                if lock.locked():
                    lock.release()
        try:
            background_tasks.add_task(sync_catalogue)
        except Exception:
            user_status['running']=False
            progress['running']=False
            if lock.locked():
                lock.release()
            raise
    token=create_token(user['id'],user['email'],request.app.state.jwt_secret,expires_hours=8)
    response.set_cookie('neodesk_token',token,httponly=True,samesite='strict',
                        secure=request.app.state.is_production,max_age=8*3600)
    response.delete_cookie('neodesk_session')
    return {'user':UserResponse(**{k:user[k] for k in ('id','email','display_name','created_at')}),
            'authenticated':True,'portfolio_sync_error':sync_error}


@auth_router.post("/register", response_model=TokenResponse)
def register(body: UserRegister, request: Request, response: Response):
    """Register a new user account and return an access token."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(_register_attempts, client_ip, 10, "registration")

    store = getattr(request.app.state, "store", None)
    if not store:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Store service unavailable",
        )

    clean_email = body.email.strip().lower()
    existing = store.get_user_by_email(clean_email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    try:
        user = create_user(store, clean_email, body.password, body.display_name)
        app_config = getattr(request.app.state, "config", settings)
        starting_bal = getattr(app_config, "paper_starting_balance", 100000)
        store.init_user_account(user["id"], starting_bal)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Registration failed"
        )


    jwt_secret = getattr(request.app.state, "jwt_secret", settings.jwt_secret)
    token = create_token(user["id"], user["email"], jwt_secret)

    response.set_cookie(
        "neodesk_token",
        token,
        httponly=True,
        samesite="lax",
        secure=getattr(request.app.state, "is_production", False),
        max_age=24 * 3600,
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            display_name=user["display_name"],
            created_at=user["created_at"],
        ),
    )


@auth_router.post("/login", response_model=TokenResponse)
def login(body: UserLogin, request: Request, response: Response):
    """Authenticate with email and password and return an access token."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(_login_attempts, client_ip, 5, "login")

    store = getattr(request.app.state, "store", None)
    if not store:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Store service unavailable",
        )

    user = authenticate_user(store, body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    jwt_secret = getattr(request.app.state, "jwt_secret", settings.jwt_secret)
    token = create_token(user["id"], user["email"], jwt_secret)

    response.set_cookie(
        "neodesk_token",
        token,
        httponly=True,
        samesite="lax",
        secure=getattr(request.app.state, "is_production", False),
        max_age=24 * 3600,
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            display_name=user["display_name"],
            created_at=user["created_at"],
        ),
    )


@auth_router.get("/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)):
    """Return the profile of the currently authenticated user."""
    return UserResponse(
        id=current_user["id"],
        email=current_user["email"],
        display_name=current_user["display_name"],
        created_at=current_user["created_at"],
    )


@auth_router.post("/logout")
def logout(request: Request, response: Response):
    """Invalidate session cookie."""
    response.delete_cookie("neodesk_token")
    response.delete_cookie('neodesk_session')
    user=getattr(request.state,'user',None)
    if user:
        request.app.state.market.disconnect(user_id=user['id'])
    return {"ok": True, "message": "Successfully logged out"}
