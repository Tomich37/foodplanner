from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TEMPLATES_DIR, settings
from app.core.csrf import csrf_input, rotate_session
from app.core.security import hash_password, verify_and_update_password
from app.db.session import get_session
from app.dependencies.users import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["static_version"] = settings.static_version
templates.env.globals["csrf_input"] = csrf_input


class LoginAttemptLimiter:
    """Ограничивает частоту попыток входа (по IP и e-mail) в памяти процесса."""

    def __init__(self, max_attempts: int, window_seconds: int, block_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self.by_ip: dict[str, list[float]] = {}
        self.by_email: dict[str, list[float]] = {}
        self.ip_blocked_until: dict[str, float] = {}
        self.email_blocked_until: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _prune(self, attempts: dict[str, list[float]], key: str, now: float) -> list[float]:
        values = [ts for ts in attempts.get(key, []) if now - ts <= self.window_seconds]
        attempts[key] = values
        return values

    async def get_block_seconds(self, ip: str, email: str) -> int:
        now = time.monotonic()
        async with self._lock:
            ip_left = max(0.0, self.ip_blocked_until.get(ip, 0.0) - now)
            email_left = max(0.0, self.email_blocked_until.get(email, 0.0) - now)
            return int(max(ip_left, email_left))

    async def register_failure(self, ip: str, email: str) -> int:
        now = time.monotonic()
        async with self._lock:
            ip_attempts = self._prune(self.by_ip, ip, now)
            email_attempts = self._prune(self.by_email, email, now)
            ip_attempts.append(now)
            email_attempts.append(now)
            if len(ip_attempts) >= self.max_attempts:
                self.ip_blocked_until[ip] = now + self.block_seconds
            if len(email_attempts) >= self.max_attempts:
                self.email_blocked_until[email] = now + self.block_seconds
            return len(email_attempts)

    async def register_success(self, ip: str, email: str) -> None:
        async with self._lock:
            self.by_ip.pop(ip, None)
            self.by_email.pop(email, None)
            self.ip_blocked_until.pop(ip, None)
            self.email_blocked_until.pop(email, None)


class AuthService:
    """Операции регистрации и входа пользователя."""

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def validate_passwords(password: str, confirm_password: str) -> list[str]:
        errors: list[str] = []
        if len(password.strip()) < 10:
            errors.append("Пароль должен содержать минимум 10 символов.")
        if password != confirm_password:
            errors.append("Пароли не совпадают.")
        return errors

    @staticmethod
    async def find_by_email(session: AsyncSession, email: str) -> User | None:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
        user = await AuthService.find_by_email(session, email)
        if not user:
            return None

        verified, replacement_hash = verify_and_update_password(password, user.password_hash)
        if not verified:
            return None

        if replacement_hash:
            user.password_hash = replacement_hash
            session.add(user)
            await session.commit()

        return user

    @staticmethod
    async def create_user(session: AsyncSession, email: str, full_name: str, password: str) -> User:
        user = User(
            email=email,
            full_name=full_name.strip() or None,
            password_hash=hash_password(password),
        )
        session.add(user)
        await session.flush()
        return user

    @staticmethod
    def set_session_user(request: Request, user: User) -> None:
        request.session.clear()
        rotate_session(request)
        request.session["user_id"] = user.id


auth_service = AuthService()
login_limiter = LoginAttemptLimiter(
    max_attempts=settings.login_max_attempts,
    window_seconds=settings.login_attempt_window_seconds,
    block_seconds=settings.login_block_seconds,
)


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@router.get("/register", response_class=HTMLResponse, name="register_form")
async def register_form(
    request: Request, current_user: User | None = Depends(get_current_user)
):
    """Отрисовывает форму регистрации, если пользователь не авторизован."""
    if current_user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "register.html",
        {"request": request, "current_user": current_user, "errors": None},
    )


@router.post("/register", response_class=HTMLResponse)
async def register_user(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Создает нового пользователя после базовой валидации."""
    errors = auth_service.validate_passwords(password, confirm_password)
    email_normalized = auth_service.normalize_email(email)

    existing = await auth_service.find_by_email(session, email_normalized)
    if existing:
        errors.append("Пользователь с таким e-mail уже существует.")

    if errors:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "errors": errors,
                "current_user": None,
                "form_email": email,
                "form_full_name": full_name,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = await auth_service.create_user(session, email_normalized, full_name, password)
    await session.commit()
    auth_service.set_session_user(request, user)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse, name="login_form")
async def login_form(
    request: Request, current_user: User | None = Depends(get_current_user)
):
    """Отрисовывает форму входа, если пользователь не авторизован."""
    if current_user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "current_user": current_user, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Проверяет учетные данные и выполняет вход пользователя."""
    email_normalized = auth_service.normalize_email(email)
    ip = _client_ip(request)

    blocked_for = await login_limiter.get_block_seconds(ip, email_normalized)
    if blocked_for > 0:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": f"Слишком много попыток входа. Повторите через {blocked_for} сек.",
                "current_user": None,
                "form_email": email,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = await auth_service.authenticate(session, email_normalized, password)
    if not user:
        fail_count = await login_limiter.register_failure(ip, email_normalized)
        await asyncio.sleep(min(fail_count, 3) * 0.25)
        logger.warning("Неудачная попытка входа: email=%s ip=%s", email_normalized, ip)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Неверный e-mail или пароль.",
                "current_user": None,
                "form_email": email,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    await login_limiter.register_success(ip, email_normalized)
    auth_service.set_session_user(request, user)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout", name="logout")
async def logout(request: Request):
    """Чистит сессию и перенаправляет на главную."""
    request.session.clear()
    rotate_session(request)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
