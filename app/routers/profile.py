from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TEMPLATES_DIR, settings
from app.core.csrf import csrf_input
from app.core.security import hash_password, verify_password
from app.db.session import get_session
from app.dependencies.users import get_current_user_required
from app.models.user import User

router = APIRouter(prefix="/profile", tags=["profile"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["static_version"] = settings.static_version
templates.env.globals["csrf_input"] = csrf_input


class ProfileService:
    """Сервис профиля: валидация и смена пароля пользователя."""

    @staticmethod
    def validate_passwords(
        current_password: str, new_password: str, confirm_password: str, user: User
    ) -> list[str]:
        errors: list[str] = []
        if not verify_password(current_password, user.password_hash):
            errors.append("Текущий пароль указан неверно.")
        if len(new_password.strip()) < 10:
            errors.append("Новый пароль должен содержать минимум 10 символов.")
        if new_password != confirm_password:
            errors.append("Пароли не совпадают.")
        return errors

    @staticmethod
    async def change_password(session: AsyncSession, user: User, new_password: str) -> None:
        user.password_hash = hash_password(new_password)
        session.add(user)
        await session.commit()


profile_service = ProfileService()


@router.get("/", response_class=HTMLResponse, name="profile")
async def profile_page(
    request: Request,
    current_user: User = Depends(get_current_user_required),
):
    """Личный кабинет с формой смены пароля."""
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "current_user": current_user, "errors": None, "success": None},
    )


@router.post("/password", response_class=HTMLResponse, name="profile_change_password")
async def change_password(
    request: Request,
    current_user: User = Depends(get_current_user_required),
    session: AsyncSession = Depends(get_session),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    """Обрабатывает смену пароля в личном кабинете."""
    errors = profile_service.validate_passwords(
        current_password, new_password, confirm_password, current_user
    )

    if errors:
        return templates.TemplateResponse(
            "profile.html",
            {
                "request": request,
                "current_user": current_user,
                "errors": errors,
                "success": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    await profile_service.change_password(session, current_user, new_password)
    success = "Пароль успешно обновлён."
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "current_user": current_user,
            "errors": None,
            "success": success,
        },
    )
