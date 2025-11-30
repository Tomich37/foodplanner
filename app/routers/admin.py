from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TEMPLATES_DIR
from app.db.session import get_session
from app.dependencies.users import get_current_user_required
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _ensure_admin(user: User) -> None:
    """Простая проверка прав администратора."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступно только администраторам.")


@router.get("/users", response_class=HTMLResponse, name="admin_users")
async def list_users(
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    """Страница управления администраторами: список пользователей и действия."""
    _ensure_admin(current_user)
    result = await session.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return templates.TemplateResponse(
        "admin_users.html",
        {"request": request, "current_user": current_user, "users": users},
    )


@router.post("/users/{user_id}/grant", response_class=HTMLResponse, name="admin_grant")
async def grant_admin(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    """Назначает пользователя администратором."""
    _ensure_admin(current_user)
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    user.is_admin = True
    await session.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/revoke", response_class=HTMLResponse, name="admin_revoke")
async def revoke_admin(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    """Снимает права администратора с выбранного пользователя."""
    _ensure_admin(current_user)
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    # Не позволяем снимать права с себя, чтобы не потерять доступ.
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя снять права с самого себя.")
    user.is_admin = False
    await session.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)
