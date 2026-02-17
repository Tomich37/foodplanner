from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TEMPLATES_DIR, settings
from app.db.session import get_session
from app.dependencies.users import get_current_user_required
from app.models import RecipeExtraTag, User

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["static_version"] = settings.static_version
TAG_VALUE_RE = re.compile(r"[^a-z0-9]+")
PRIMARY_TAG_VALUES = {"breakfast", "lunch", "dinner"}


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


async def _fetch_extra_tags(session: AsyncSession, *, order_desc: bool = False) -> list[RecipeExtraTag]:
    stmt = select(RecipeExtraTag)
    if order_desc:
        stmt = stmt.order_by(RecipeExtraTag.created_at.desc())
    else:
        stmt = stmt.order_by(RecipeExtraTag.label.asc())
    result = await session.execute(stmt)
    return result.scalars().all()


def _normalize_tag_value(raw: str) -> str:
    slug = TAG_VALUE_RE.sub("-", raw.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:32]


async def _render_tags_page(
    request: Request,
    session: AsyncSession,
    current_user: User,
    *,
    form_error: str | None = None,
) -> HTMLResponse:
    tags = await _fetch_extra_tags(session, order_desc=True)
    return templates.TemplateResponse(
        "admin_tags.html",
        {
            "request": request,
            "current_user": current_user,
            "tags": tags,
            "form_error": form_error,
        },
        status_code=status.HTTP_400_BAD_REQUEST if form_error else status.HTTP_200_OK,
    )


@router.get("/tags", response_class=HTMLResponse, name="admin_tags")
async def admin_tags(
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    tags = await _fetch_extra_tags(session, order_desc=True)
    return templates.TemplateResponse(
        "admin_tags.html",
        {
            "request": request,
            "current_user": current_user,
            "tags": tags,
            "form_error": None,
        },
    )


@router.post("/tags", response_class=HTMLResponse, name="admin_create_tag")
async def admin_create_tag(
    request: Request,
    label: str = Form(...),
    value: str = Form(""),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    clean_label = (label or "").strip()
    clean_value = (value or "").strip()
    if not clean_label:
        return await _render_tags_page(request, session, current_user, form_error="Название обязательно.")
    slug = _normalize_tag_value(clean_value or clean_label)
    if not slug:
        return await _render_tags_page(
            request, session, current_user, form_error="Ключ должен содержать латинские символы или цифры."
        )
    if slug in PRIMARY_TAG_VALUES:
        return await _render_tags_page(
            request, session, current_user, form_error="Этот ключ зарезервирован для основных тегов."
        )
    existing = await session.execute(select(RecipeExtraTag).where(RecipeExtraTag.value == slug))
    if existing.scalar_one_or_none():
        return await _render_tags_page(
            request, session, current_user, form_error="Тег с таким ключом уже существует."
        )
    session.add(RecipeExtraTag(value=slug, label=clean_label))
    await session.commit()
    return RedirectResponse(url="/admin/tags", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tags/{tag_id}/delete", response_class=HTMLResponse, name="admin_delete_tag")
async def admin_delete_tag(
    tag_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    tag = await session.get(RecipeExtraTag, tag_id)
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тег не найден.")
    await session.delete(tag)
    await session.flush()
    await session.execute(
        text("UPDATE recipes SET tags = array_remove(tags, :value) WHERE :value = ANY(tags)"),
        {"value": tag.value},
    )
    await session.commit()
    return RedirectResponse(url="/admin/tags", status_code=status.HTTP_303_SEE_OTHER)


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
