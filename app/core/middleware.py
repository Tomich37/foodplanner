from __future__ import annotations

from urllib.parse import urlparse

from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _normalize_origin(value: str | None) -> str | None:
    if not value:
        return None

    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None

    host = parsed.hostname.lower()
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    return f"{parsed.scheme}://{host}:{port}"


def _extract_first_header_value(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(",", maxsplit=1)[0].strip()


def _collect_allowed_origins(request: Request) -> set[str]:
    allowed: set[str] = set()

    for configured_origin in settings.csrf_trusted_origins:
        normalized = _normalize_origin(configured_origin)
        if normalized:
            allowed.add(normalized)

    base_normalized = _normalize_origin(str(request.base_url))
    if base_normalized:
        allowed.add(base_normalized)

    forwarded_proto = _extract_first_header_value(request.headers.get("x-forwarded-proto"))
    scheme = forwarded_proto or request.url.scheme

    for header_name in ("x-forwarded-host", "host"):
        header_value = _extract_first_header_value(request.headers.get(header_name))
        if not header_value:
            continue
        normalized = _normalize_origin(f"{scheme}://{header_value}")
        if normalized:
            allowed.add(normalized)

    return allowed


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers[
            "Content-Security-Policy"
        ] = (
            "default-src 'self'; "
            "img-src 'self' data: https://mc.yandex.ru https://mc.yandex.com https://*.yandex.ru https://*.yandex.com https://yastatic.net https://*.yastatic.net; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'sha256-Yn0rko3bCH+jo4pn2Y7vA2ETS9s/qUPj+V7Bbtyjy/s=' https://mc.yandex.ru https://mc.yandex.com https://yastatic.net https://*.yastatic.net https://static.cloudflareinsights.com; "
            "connect-src 'self' https://mc.yandex.ru https://mc.yandex.com https://*.yandex.ru https://*.yandex.com https://cloudflareinsights.com https://static.cloudflareinsights.com wss://mc.yandex.com wss://*.yandex.com; "
            "frame-src 'self' https://mc.yandex.ru https://mc.yandex.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        return response


class MultipartBodyLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type:
                content_length = request.headers.get("content-length")
                if content_length:
                    try:
                        size = int(content_length)
                    except ValueError:
                        size = 0
                    if size > settings.max_multipart_body_bytes:
                        return JSONResponse(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            content={"detail": "Слишком большой размер запроса."},
                        )
        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in SAFE_METHODS or request.url.path.startswith("/static"):
            return await call_next(request)

        # Не читаем body в middleware: иначе FastAPI может не получить поля формы.
        # Проверяем same-origin через Origin/Referer.
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        is_valid_origin = True
        if origin or referer:
            provided_origin = _normalize_origin(origin) or _normalize_origin(referer)
            allowed_origins = _collect_allowed_origins(request)
            is_valid_origin = provided_origin is not None and provided_origin in allowed_origins

        if not is_valid_origin:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Некорректный источник запроса (CSRF)."},
            )

        return await call_next(request)
