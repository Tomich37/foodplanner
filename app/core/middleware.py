from __future__ import annotations

from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


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
            "img-src 'self' data: https://mc.yandex.ru https://mc.yandex.com https://*.yandex.ru https://*.yandex.com; "
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
        base_url = str(request.base_url).rstrip("/")
        allowed_origin = base_url

        is_valid_origin = True
        if origin:
            is_valid_origin = origin.rstrip("/") == allowed_origin
        elif referer:
            is_valid_origin = referer.startswith(base_url + "/") or referer == base_url

        if not is_valid_origin:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Некорректный источник запроса (CSRF)."},
            )

        return await call_next(request)
