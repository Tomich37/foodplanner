from __future__ import annotations

import re
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import TEMPLATES_DIR, settings
from app.core.csrf import csrf_input
from app.core.security import hash_password
from app.db.session import get_session
from app.dependencies.users import get_current_user_required
from app.models import IngredientAlias, IngredientCanonical, RecipeExtraTag, User
from app.services.ingredient_catalog import (
    attach_aliases_to_canonical,
    get_or_create_canonical,
    normalize_ingredient_name,
    sync_catalog_from_recipe_ingredients,
)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["static_version"] = settings.static_version
templates.env.globals["csrf_input"] = csrf_input
TAG_VALUE_RE = re.compile(r"[^a-z0-9]+")
PRIMARY_TAG_VALUES = {"breakfast", "lunch", "dinner"}


def _ensure_admin(user: User) -> None:
    """Простая проверка прав администратора."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступно только администраторам.")


async def _get_user_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден.")
    return user


async def _render_users_page(
    request: Request,
    session: AsyncSession,
    current_user: User,
    *,
    form_error: str | None = None,
) -> HTMLResponse:
    result = await session.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return templates.TemplateResponse(
        "admin_users.html",
        {
            "request": request,
            "current_user": current_user,
            "users": users,
            "form_error": form_error,
        },
        status_code=status.HTTP_400_BAD_REQUEST if form_error else status.HTTP_200_OK,
    )


@router.get("/users", response_class=HTMLResponse, name="admin_users")
async def list_users(
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    """Страница управления администраторами: список пользователей и действия."""
    _ensure_admin(current_user)
    return await _render_users_page(request, session, current_user)


@router.post("/users/{user_id}/grant", response_class=HTMLResponse, name="admin_grant")
async def grant_admin(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    """Назначает пользователя администратором."""
    _ensure_admin(current_user)
    user = await _get_user_or_404(session, user_id)
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


def _split_aliases(raw_value: str) -> list[str]:
    parts = re.split(r"[,\n;]+", raw_value or "")
    return [part.strip() for part in parts if part.strip()]


async def _fetch_ingredient_catalog(session: AsyncSession) -> list[IngredientCanonical]:
    result = await session.execute(
        select(IngredientCanonical)
        .options(selectinload(IngredientCanonical.aliases))
        .order_by(IngredientCanonical.name.asc())
    )
    return result.scalars().all()


async def _render_ingredients_page(
    request: Request,
    session: AsyncSession,
    current_user: User,
    *,
    form_error: str | None = None,
    info_message: str | None = None,
) -> HTMLResponse:
    catalog = await _fetch_ingredient_catalog(session)
    alias_count = sum(len(item.aliases) for item in catalog)
    return templates.TemplateResponse(
        "admin_ingredients.html",
        {
            "request": request,
            "current_user": current_user,
            "catalog": catalog,
            "alias_count": alias_count,
            "form_error": form_error,
            "info_message": info_message,
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


@router.get("/ingredients", response_class=HTMLResponse, name="admin_ingredients")
async def admin_ingredients(
    request: Request,
    message: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    return await _render_ingredients_page(
        request,
        session,
        current_user,
        info_message=message,
    )


@router.post("/ingredients", response_class=HTMLResponse, name="admin_create_ingredient_mapping")
async def admin_create_ingredient_mapping(
    request: Request,
    canonical_name: str = Form(...),
    aliases: str = Form(""),
    overwrite_existing: bool = Form(False),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    clean_canonical = (canonical_name or "").strip()
    if not clean_canonical:
        return await _render_ingredients_page(
            request, session, current_user, form_error="Название канонического ингредиента обязательно."
        )

    normalized_canonical = normalize_ingredient_name(clean_canonical)
    if not normalized_canonical:
        return await _render_ingredients_page(
            request, session, current_user, form_error="Название не удалось нормализовать."
        )

    canonical = await get_or_create_canonical(
        session,
        normalized_canonical,
        display_name=normalized_canonical,
    )
    if not canonical:
        return await _render_ingredients_page(
            request, session, current_user, form_error="Не удалось создать канонический ингредиент."
        )

    alias_values = [clean_canonical, *_split_aliases(aliases)]
    created_aliases, conflicts = await attach_aliases_to_canonical(
        session,
        canonical,
        alias_values,
        overwrite_existing=overwrite_existing,
    )
    if conflicts:
        return await _render_ingredients_page(
            request,
            session,
            current_user,
            form_error=(
                "Эти алиасы уже привязаны к другим ингредиентам: "
                + ", ".join(sorted({normalize_ingredient_name(value) for value in conflicts}))
                + "."
            ),
        )

    await session.commit()
    message = f"Обновлено. Канон: {canonical.name}. Добавлено алиасов: {created_aliases}."
    return RedirectResponse(
        url=f"/admin/ingredients?message={quote_plus(message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/ingredients/sync", response_class=HTMLResponse, name="admin_sync_ingredients")
async def admin_sync_ingredients(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    stats = await sync_catalog_from_recipe_ingredients(session)
    await session.commit()
    message = (
        f"Синхронизация завершена. Новых канонов: {stats.created_canonicals}, "
        f"новых алиасов: {stats.created_aliases}."
    )
    return RedirectResponse(
        url=f"/admin/ingredients?message={quote_plus(message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/ingredients/aliases/{alias_id}/delete", response_class=HTMLResponse, name="admin_delete_ingredient_alias")
async def admin_delete_ingredient_alias(
    alias_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    alias = await session.get(IngredientAlias, alias_id)
    if not alias:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Алиас не найден.")
    await session.delete(alias)
    await session.commit()
    return RedirectResponse(url="/admin/ingredients", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ingredients/{ingredient_id}/delete", response_class=HTMLResponse, name="admin_delete_ingredient")
async def admin_delete_ingredient(
    ingredient_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    ingredient = await session.get(IngredientCanonical, ingredient_id)
    if not ingredient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ингредиент не найден.")
    await session.delete(ingredient)
    await session.commit()
    return RedirectResponse(url="/admin/ingredients", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/revoke", response_class=HTMLResponse, name="admin_revoke")
async def revoke_admin(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    """Снимает права администратора с выбранного пользователя."""
    _ensure_admin(current_user)
    user = await _get_user_or_404(session, user_id)
    # Не позволяем снимать права с себя, чтобы не потерять доступ.
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя снять права с самого себя.")
    user.is_admin = False
    await session.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/ban", response_class=HTMLResponse, name="admin_ban")
async def ban_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    user = await _get_user_or_404(session, user_id)
    user.is_banned = True
    await session.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/unban", response_class=HTMLResponse, name="admin_unban")
async def unban_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    user = await _get_user_or_404(session, user_id)
    user.is_banned = False
    await session.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/password", response_class=HTMLResponse, name="admin_user_password")
async def change_user_password(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    _ensure_admin(current_user)
    clean_password = (new_password or "").strip()
    if len(clean_password) < 10:
        return await _render_users_page(
            request, session, current_user, form_error="Пароль должен содержать минимум 6 символов."
        )
    user = await _get_user_or_404(session, user_id)
    user.password_hash = hash_password(clean_password)
    await session.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)
