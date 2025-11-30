from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TEMPLATES_DIR
from app.core.security import hash_password, verify_password
from app.db.session import get_session
from app.dependencies.users import get_current_user
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class AuthService:
    """Простая обертка над операциями регистрации и логина (валидация, поиск пользователя)."""

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def validate_passwords(password: str, confirm_password: str) -> list[str]:
        errors: list[str] = []
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
        if not user or not verify_password(password, user.password_hash):
            return None
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
        request.session["user_id"] = user.id


auth_service = AuthService()


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
    """Отрисовывает форму логина, если пользователь не авторизован."""
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
    """Проверяет учетные данные и логинит пользователя."""
    email_normalized = auth_service.normalize_email(email)
    user = await auth_service.authenticate(session, email_normalized, password)
    if not user:
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
    auth_service.set_session_user(request, user)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout", name="logout")
async def logout(request: Request):
    """Чистит сессию и перенаправляет на главную."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
