"""Authentication service module."""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import bcrypt
import jwt


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_token(user_id: int, email: str, secret: str, expires_hours: int = 24) -> str:
    """Generate a JWT token for the authenticated user using HS256."""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    """Decode and validate a JWT token; returns {'user_id': int, 'email': str}."""
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    return {
        "user_id": int(payload["user_id"]),
        "email": str(payload["email"]),
    }


def create_user(store, email: str, password: str, display_name: str) -> dict:
    """Create a new user in the store after hashing the password."""
    clean_email = email.strip().lower()
    existing = store.get_user_by_email(clean_email)
    if existing:
        raise ValueError("Email already registered")
    password_hash = hash_password(password)
    return store.create_user(clean_email, password_hash, display_name.strip())


def authenticate_user(store, email: str, password: str) -> Optional[Dict[str, Any]]:
    """Verify user credentials and return user info or None."""
    clean_email = email.strip().lower()
    user = store.get_user_by_email(clean_email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "created_at": user["created_at"],
    }
