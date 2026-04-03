from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response, status

from app.core.config import Settings, get_settings


SESSION_COOKIE_NAME = "arr_inventory_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 12
FREE_LOGIN_ATTEMPTS = 3
MAX_LOGIN_DELAY_SECONDS = 300


@dataclass(slots=True)
class LoginThrottleState:
    failures: int = 0
    next_allowed_at: float = 0.0


LOGIN_THROTTLE: dict[str, LoginThrottleState] = {}


def authenticate_admin(username: str, password: str, settings: Settings) -> bool:
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(password, settings.admin_password)


def enforce_login_rate_limit(request: Request) -> None:
    client_ip = get_client_ip(request)
    state = LOGIN_THROTTLE.get(client_ip)
    if state is None:
        return

    now = time.monotonic()
    if now >= state.next_allowed_at:
        return

    updated_state = register_failed_login_attempt(request)
    retry_after = max(1, int(updated_state.next_allowed_at - now))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many login attempts. Try again in {retry_after}s.",
    )


def register_failed_login_attempt(request: Request) -> LoginThrottleState:
    client_ip = get_client_ip(request)
    state = LOGIN_THROTTLE.get(client_ip, LoginThrottleState())
    state.failures += 1
    delay = calculate_login_delay_seconds(state.failures)
    state.next_allowed_at = time.monotonic() + delay if delay else 0.0
    LOGIN_THROTTLE[client_ip] = state
    return state


def clear_login_throttle(request: Request) -> None:
    LOGIN_THROTTLE.pop(get_client_ip(request), None)


def reset_login_throttle_state() -> None:
    LOGIN_THROTTLE.clear()


def calculate_login_delay_seconds(failures: int) -> int:
    if failures < FREE_LOGIN_ATTEMPTS:
        return 0
    exponent = failures - FREE_LOGIN_ATTEMPTS
    return min(MAX_LOGIN_DELAY_SECONDS, 2**exponent)


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded_for:
        return forwarded_for
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def require_authenticated_admin(request: Request, settings: Settings = Depends(get_settings)) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    username = verify_session_token(token, settings)
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return username


def build_session_response(request: Request, settings: Settings) -> dict[str, str | bool]:
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    username = verify_session_token(token, settings)
    if username is None:
        return {"authenticated": False}
    return {"authenticated": True, "username": username}


def set_authenticated_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(settings),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
    )


def clear_authenticated_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, httponly=True, samesite="lax", secure=False)


def create_session_token(settings: Settings) -> str:
    payload = {
        "sub": settings.admin_username,
        "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded_payload = _urlsafe_b64encode(payload_bytes)
    signature = hmac.new(_session_secret(settings), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_urlsafe_b64encode(signature)}"


def verify_session_token(token: str, settings: Settings) -> str | None:
    if not token or "." not in token:
        return None
    encoded_payload, encoded_signature = token.split(".", 1)
    expected_signature = hmac.new(_session_secret(settings), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    actual_signature = _urlsafe_b64decode(encoded_signature)
    if actual_signature is None or not hmac.compare_digest(actual_signature, expected_signature):
        return None
    payload_bytes = _urlsafe_b64decode(encoded_payload)
    if payload_bytes is None:
        return None
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    username = str(payload.get("sub") or "")
    expires_at = int(payload.get("exp") or 0)
    if not username or username != settings.admin_username:
        return None
    if expires_at <= int(time.time()):
        return None
    return username


def _session_secret(settings: Settings) -> bytes:
    return f"{settings.app_name}:{settings.admin_username}:{settings.admin_password}".encode("utf-8")


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes | None:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None
