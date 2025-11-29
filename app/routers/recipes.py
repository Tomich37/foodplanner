from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import STATIC_DIR, TEMPLATES_DIR
from app.db.session import get_session
from app.dependencies.users import get_current_user, get_current_user_required
from app.models import Recipe, RecipeIngredient, RecipeStep, User

router = APIRouter(prefix="/recipes", tags=["recipes"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
UPLOADS_DIR = STATIC_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

AVAILABLE_TAGS = [
    {"value": "breakfast", "label": "Завтрак"},
    {"value": "lunch", "label": "Обед"},
    {"value": "dinner", "label": "Ужин"},
    {"value": "dessert", "label": "Десерт"},
    {"value": "snack", "label": "Снеки"},
    {"value": "pp", "label": "ПП"},
]
TAG_VALUE_SET = {item["value"] for item in AVAILABLE_TAGS}
TAG_LABELS = {item["value"]: item["label"] for item in AVAILABLE_TAGS}


def _recipes_query():
    return select(Recipe).options(
        selectinload(Recipe.steps),
        selectinload(Recipe.ingredients),
        selectinload(Recipe.author),
    )


def _prepare_ingredients(names: Iterable[str], amounts: Iterable[float]) -> list[tuple[str, float]]:
    items: list[tuple[str, float]] = []
    for name, amount in zip(names, amounts):
        clean_name = (name or "").strip()
        if not clean_name:
            continue
        try:
            parsed_amount = float(amount)
        except (TypeError, ValueError):
            continue
        if parsed_amount <= 0:
            continue
        items.append((clean_name, parsed_amount))
    return items


def _validate_common_fields(title: str, steps: list[str], ingredients: list[tuple[str, float]]):
    if not title.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Укажите название блюда")
    if not steps:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Добавьте хотя бы один шаг")
    if not ingredients:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Добавьте хотя бы один ингредиент")


def _normalize_tags(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        if value not in TAG_VALUE_SET or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


async def _save_upload(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None
    suffix = Path(upload.filename).suffix.lower()
    filename = f"{uuid.uuid4().hex}{suffix}"
    destination = UPLOADS_DIR / filename
    data = await upload.read()
    destination.write_bytes(data)
    return f"/static/uploads/{filename}"


async def _load_recipe(session: AsyncSession, recipe_id: int) -> Recipe:
    result = await session.execute(_recipes_query().where(Recipe.id == recipe_id))
    recipe = result.scalar_one_or_none()
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Рецепт не найден")
    return recipe


@router.get("/", response_class=HTMLResponse, name="recipes_list")
async def recipes_list(
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    result = await session.execute(_recipes_query().order_by(Recipe.created_at.desc()))
    recipes = result.scalars().all()
    return templates.TemplateResponse(
        "recipes_list.html",
        {
            "request": request,
            "current_user": current_user,
            "recipes": recipes,
            "tag_labels": TAG_LABELS,
        },
    )


@router.get("/new", response_class=HTMLResponse, name="recipes_new")
async def new_recipe(request: Request, current_user: User = Depends(get_current_user_required)):
    return templates.TemplateResponse(
        "recipe_new.html",
        {"request": request, "current_user": current_user, "available_tags": AVAILABLE_TAGS},
    )


@router.post("/", response_class=HTMLResponse, name="create_recipe")
async def create_recipe(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    steps: list[str] = Form(...),
    ingredient_names: list[str] = Form([]),
    ingredient_amounts: list[float] = Form([]),
    tags: list[str] = Form([]),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
    cover_image: UploadFile | None = File(None),
    step_images: list[UploadFile] | None = File(None),
):
    step_texts = [text.strip() for text in steps if text.strip()]
    ingredients = _prepare_ingredients(ingredient_names, ingredient_amounts)
    selected_tags = _normalize_tags(tags)
    _validate_common_fields(title, step_texts, ingredients)

    recipe = Recipe(
        title=title.strip(),
        description=description.strip() or None,
        image_path=await _save_upload(cover_image),
        author=current_user,
        tags=selected_tags,
        steps=[],
        ingredients=[],
    )
    session.add(recipe)
    await session.flush()

    image_list = step_images or []
    for idx, instruction in enumerate(step_texts, start=1):
        image = image_list[idx - 1] if idx - 1 < len(image_list) else None
        recipe.steps.append(
            RecipeStep(
                position=idx,
                instruction=instruction,
                image_path=await _save_upload(image),
            )
        )

    for name, amount in ingredients:
        recipe.ingredients.append(RecipeIngredient(name=name, amount=amount))

    await session.commit()
    return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{recipe_id}/edit", response_class=HTMLResponse, name="recipes_edit")
async def edit_recipe(
    request: Request,
    recipe_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    recipe = await _load_recipe(session, recipe_id)
    if recipe.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Можно редактировать только свои рецепты")

    return templates.TemplateResponse(
        "recipe_edit.html",
        {
            "request": request,
            "current_user": current_user,
            "recipe": recipe,
            "available_tags": AVAILABLE_TAGS,
        },
    )


@router.post("/{recipe_id}/edit", response_class=HTMLResponse, name="update_recipe")
async def update_recipe(
    request: Request,
    recipe_id: int,
    title: str = Form(...),
    description: str = Form(""),
    steps: list[str] = Form(...),
    ingredient_names: list[str] = Form([]),
    ingredient_amounts: list[float] = Form([]),
    tags: list[str] = Form([]),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
    cover_image: UploadFile | None = File(None),
    step_images: list[UploadFile] | None = File(None),
):
    recipe = await _load_recipe(session, recipe_id)
    if recipe.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Можно редактировать только свои рецепты")

    step_texts = [text.strip() for text in steps if text.strip()]
    ingredients = _prepare_ingredients(ingredient_names, ingredient_amounts)
    selected_tags = _normalize_tags(tags)
    _validate_common_fields(title, step_texts, ingredients)

    recipe.title = title.strip()
    recipe.description = description.strip() or None
    recipe.tags = selected_tags

    new_cover = await _save_upload(cover_image)
    if new_cover:
        recipe.image_path = new_cover

    recipe.steps.clear()
    recipe.ingredients.clear()
    await session.flush()

    image_list = step_images or []
    for idx, instruction in enumerate(step_texts, start=1):
        image = image_list[idx - 1] if idx - 1 < len(image_list) else None
        recipe.steps.append(
            RecipeStep(
                position=idx,
                instruction=instruction,
                image_path=await _save_upload(image),
            )
        )

    for name, amount in ingredients:
        recipe.ingredients.append(RecipeIngredient(name=name, amount=amount))

    await session.commit()
    return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{recipe_id}", response_class=HTMLResponse, name="recipe_detail")
async def recipe_detail(
    request: Request,
    recipe_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    recipe = await _load_recipe(session, recipe_id)
    return templates.TemplateResponse(
        "recipe_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "recipe": recipe,
            "tag_labels": TAG_LABELS,
        },
    )
