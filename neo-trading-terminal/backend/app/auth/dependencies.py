"""Authentication dependencies for FastAPI endpoints."""
from fastapi import HTTPException, Request, status
from app.core.config import settings
from app.auth.service import decode_token


def get_current_user(request: Request) -> dict:
    """Extract and validate the current user from JWT in Authorization header or cookie."""
    # If already validated and stored on request.state by protect middleware:
    if hasattr(request.state, "user") and request.state.user:
        return request.state.user

    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "neodesk_token" in request.cookies:
        token = request.cookies.get("neodesk_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required"
        )

    jwt_secret = getattr(request.app.state, "jwt_secret", settings.jwt_secret)
    try:
        payload = decode_token(token, jwt_secret)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    store = getattr(request.app.state, "store", None)
    if not store:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Store service unavailable"
        )

    user = store.get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    user_data = {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "created_at": user["created_at"],
    }
    request.state.user = user_data
    return user_data


def get_request_user_id(request: Request | None) -> int:
    """Resolve authenticated user id, allowing legacy/test single-user mode only when marked."""
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to your terminal.",
        )
    user = getattr(request.state, "user", None)
    if user and user.get("id"):
        return int(user["id"])
    legacy_uid = getattr(request.state, "legacy_user_id", None)
    if legacy_uid is not None:
        return int(legacy_uid)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in to your terminal.",
    )
