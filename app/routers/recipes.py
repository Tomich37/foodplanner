from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Text, cast, select
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import STATIC_DIR, TEMPLATES_DIR
from app.db.session import get_session
from app.dependencies.users import get_current_user, get_current_user_required
from app.models import Recipe, RecipeIngredient, RecipeStep, User

router = APIRouter(prefix="/recipes", tags=["recipes"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
UPLOADS_DIR = STATIC_DIR / "uploads"


@dataclass(frozen=True)
class RecipeTag:
    """Описывает доступный тег рецепта (для фильтров и форм)."""

    value: str
    label: str


class RecipeService:
    """Инкапсулирует операции с рецептами: выборки, валидацию, сохранение файлов."""

    def __init__(self, uploads_dir: Path, tags: Sequence[RecipeTag]):
        self.uploads_dir = uploads_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.tags: tuple[RecipeTag, ...] = tuple(tags)
        self.tag_value_set: set[str] = {tag.value for tag in tags}
        self.tag_labels: dict[str, str] = {tag.value: tag.label for tag in tags}

    @property
    def available_tags(self) -> list[dict[str, str]]:
        return [{"value": tag.value, "label": tag.label} for tag in self.tags]

    def base_query(self):
        return select(Recipe).options(
            selectinload(Recipe.steps),
            selectinload(Recipe.ingredients),
            selectinload(Recipe.author),
        )

    def normalize_tags(self, values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for value in values:
            if value not in self.tag_value_set or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    def prepare_ingredients(self, names: Iterable[str], amounts: Iterable[float]) -> list[tuple[str, float]]:
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

    def validate_common_fields(self, title: str, steps: list[str], ingredients: list[tuple[str, float]]):
        if not title.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Название рецепта обязательно")
        if not steps:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Добавьте хотя бы один шаг")
        if not ingredients:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Добавьте хотя бы один ингредиент")

    def clean_steps(self, steps: Iterable[str]) -> list[str]:
        return [text.strip() for text in steps if text.strip()]

    async def save_upload(self, upload: UploadFile | None) -> str | None:
        if not upload or not upload.filename:
            return None
        suffix = Path(upload.filename).suffix.lower()
        filename = f"{uuid.uuid4().hex}{suffix}"
        destination = self.uploads_dir / filename
        destination.write_bytes(await upload.read())
        return f"/static/uploads/{filename}"

    async def load_recipe(self, session: AsyncSession, recipe_id: int) -> Recipe:
        result = await session.execute(self.base_query().where(Recipe.id == recipe_id))
        recipe = result.scalar_one_or_none()
        if recipe is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Рецепт не найден")
        return recipe

    def ensure_owner(self, recipe: Recipe, current_user: User):
        if recipe.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Рецепт доступен только автору",
            )

    async def fill_recipe(
        self,
        recipe: Recipe,
        step_texts: Sequence[str],
        ingredients: Sequence[tuple[str, float]],
        step_images: Sequence[UploadFile] | None,
    ) -> None:
        recipe.steps.clear()
        recipe.ingredients.clear()

        images = list(step_images or [])
        for idx, instruction in enumerate(step_texts, start=1):
            image = images[idx - 1] if idx - 1 < len(images) else None
            recipe.steps.append(
                RecipeStep(
                    position=idx,
                    instruction=instruction,
                    image_path=await self.save_upload(image),
                )
            )

        for name, amount in ingredients:
            recipe.ingredients.append(RecipeIngredient(name=name, amount=amount))

    def apply_tag_filter(self, query, selected_tags: list[str]):
        if not selected_tags:
            return query
        tag_array = cast(
            array(selected_tags, type_=ARRAY(Text())),
            ARRAY(Text()),
        )
        return query.where(Recipe.tags.contains(tag_array))


RECIPE_TAGS = (
    RecipeTag(value="breakfast", label="Завтрак"),
    RecipeTag(value="lunch", label="Обед"),
    RecipeTag(value="dinner", label="Ужин"),
    RecipeTag(value="dessert", label="Десерт"),
    RecipeTag(value="snack", label="Перекус"),
    RecipeTag(value="pp", label="ПП"),
)
recipe_service = RecipeService(UPLOADS_DIR, RECIPE_TAGS)


@router.get("/", response_class=HTMLResponse, name="recipes_list")
async def recipes_list(
    request: Request,
    tags: list[str] = Query([]),
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    """Список рецептов с фильтрацией по тегам."""
    selected_tags = recipe_service.normalize_tags(tags)
    query = recipe_service.apply_tag_filter(
        recipe_service.base_query().order_by(Recipe.created_at.desc()),
        selected_tags,
    )
    result = await session.execute(query)
    recipes = result.scalars().all()
    return templates.TemplateResponse(
        "recipes_list.html",
        {
            "request": request,
            "current_user": current_user,
            "recipes": recipes,
            "tag_labels": recipe_service.tag_labels,
            "available_tags": recipe_service.available_tags,
            "selected_tags": selected_tags,
        },
    )


@router.get("/new", response_class=HTMLResponse, name="recipes_new")
async def new_recipe(request: Request, current_user: User = Depends(get_current_user_required)):
    """Форма добавления нового рецепта."""
    return templates.TemplateResponse(
        "recipe_new.html",
        {
            "request": request,
            "current_user": current_user,
            "available_tags": recipe_service.available_tags,
        },
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
    """Создает рецепт и сохраняет шаги/ингредиенты."""
    step_texts = recipe_service.clean_steps(steps)
    ingredients = recipe_service.prepare_ingredients(ingredient_names, ingredient_amounts)
    selected_tags = recipe_service.normalize_tags(tags)
    recipe_service.validate_common_fields(title, step_texts, ingredients)

    recipe = Recipe(
        title=title.strip(),
        description=description.strip() or None,
        image_path=await recipe_service.save_upload(cover_image),
        author=current_user,
        tags=selected_tags,
        steps=[],
        ingredients=[],
    )
    session.add(recipe)
    await session.flush()

    await recipe_service.fill_recipe(recipe, step_texts, ingredients, step_images)

    await session.commit()
    return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{recipe_id}/edit", response_class=HTMLResponse, name="recipes_edit")
async def edit_recipe(
    request: Request,
    recipe_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    """Редактор рецепта (доступен только автору)."""
    recipe = await recipe_service.load_recipe(session, recipe_id)
    recipe_service.ensure_owner(recipe, current_user)

    return templates.TemplateResponse(
        "recipe_edit.html",
        {
            "request": request,
            "current_user": current_user,
            "recipe": recipe,
            "available_tags": recipe_service.available_tags,
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
    """Обновляет рецепт: текст, шаги, ингредиенты, изображения."""
    recipe = await recipe_service.load_recipe(session, recipe_id)
    recipe_service.ensure_owner(recipe, current_user)

    step_texts = recipe_service.clean_steps(steps)
    ingredients = recipe_service.prepare_ingredients(ingredient_names, ingredient_amounts)
    selected_tags = recipe_service.normalize_tags(tags)
    recipe_service.validate_common_fields(title, step_texts, ingredients)

    recipe.title = title.strip()
    recipe.description = description.strip() or None
    recipe.tags = selected_tags

    new_cover = await recipe_service.save_upload(cover_image)
    if new_cover:
        recipe.image_path = new_cover

    await recipe_service.fill_recipe(recipe, step_texts, ingredients, step_images)

    await session.commit()
    return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{recipe_id}/delete", response_class=HTMLResponse, name="delete_recipe")
async def delete_recipe(
    request: Request,
    recipe_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    """Удаляет рецепт автора."""
    recipe = await recipe_service.load_recipe(session, recipe_id)
    recipe_service.ensure_owner(recipe, current_user)
    await session.delete(recipe)
    await session.commit()
    return RedirectResponse(url="/recipes", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{recipe_id}", response_class=HTMLResponse, name="recipe_detail")
async def recipe_detail(
    request: Request,
    recipe_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    """Детальная страница рецепта."""
    recipe = await recipe_service.load_recipe(session, recipe_id)
    return templates.TemplateResponse(
        "recipe_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "recipe": recipe,
            "tag_labels": recipe_service.tag_labels,
        },
    )
