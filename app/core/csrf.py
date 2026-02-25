import html
import secrets

from fastapi import Request
from markupsafe import Markup

CSRF_SESSION_KEY = "csrf_token"
SESSION_ID_KEY = "session_id"


def get_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def rotate_session(request: Request) -> None:
    """Rotate non-authenticated session markers to reduce fixation risk."""
    request.session[SESSION_ID_KEY] = secrets.token_urlsafe(16)
    request.session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)


def csrf_input(request: Request) -> Markup:
    token = get_csrf_token(request)
    escaped = html.escape(token, quote=True)
    return Markup(f'<input type="hidden" name="csrf_token" value="{escaped}" />')


def validate_csrf(request: Request, provided_token: str | None) -> bool:
    expected = request.session.get(CSRF_SESSION_KEY)
    if not expected or not provided_token:
        return False
    return secrets.compare_digest(expected, provided_token)
