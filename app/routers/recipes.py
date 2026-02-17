from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import cast, func, or_, select, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import STATIC_DIR, TEMPLATES_DIR, settings
from app.db.session import get_session
from app.dependencies.users import get_current_user, get_current_user_required
from app.models import Recipe, RecipeIngredient, RecipeStep, User, RecipeExtraTag
from app.services.cover_resolver import recipe_cover_resolver
from app.services.unit_converter import UnitConverter

router = APIRouter(prefix="/recipes", tags=["recipes"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
UPLOADS_DIR = STATIC_DIR / "uploads"
# Глобальный helper в шаблонах для выбора обложки с учётом заглушек.
templates.env.globals["cover_url"] = recipe_cover_resolver.resolve
unit_converter = UnitConverter()
templates.env.globals["format_amount"] = unit_converter.format_human
templates.env.globals["static_version"] = settings.static_version


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

    def normalize_tags(self, values: Iterable[str], extra_allowed: Iterable[str] | None = None) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        allowed = set(self.tag_value_set)
        if extra_allowed:
            allowed.update(extra_allowed)
        for value in values:
            if value not in allowed or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    def prepare_ingredients(
        self, names: Iterable[str], amounts: Iterable[float], units: Iterable[str]
    ) -> list[tuple[str, float, str]]:
        items: list[tuple[str, float, str]] = []
        names_list = list(names)
        amounts_list = list(amounts)
        units_list = list(units)
        for idx, (name, amount) in enumerate(zip(names_list, amounts_list)):
            clean_name = (name or "").strip()
            if not clean_name:
                continue
            unit_raw = units_list[idx] if idx < len(units_list) else None
            normalized_unit = unit_converter.normalize_unit(unit_raw)
            if normalized_unit == "taste":
                items.append((clean_name, 0.0, normalized_unit))
                continue
            try:
                parsed_amount = float(amount)
            except (TypeError, ValueError):
                continue
            if parsed_amount <= 0:
                continue
            items.append((clean_name, parsed_amount, normalized_unit))
        return items

    def validate_common_fields(self, title: str, steps: list[str], ingredients: list[tuple[str, float, str]]):
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

    def ensure_can_manage(self, recipe: Recipe, current_user: User):
        """Проверяет права: автор или администратор могут редактировать/удалять рецепт."""
        if current_user.is_admin or recipe.user_id == current_user.id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Рецепт доступен только автору или администратору",
        )

    async def fill_recipe(
        self,
        recipe: Recipe,
        step_texts: Sequence[str],
        ingredients: Sequence[tuple[str, float, str]],
        step_images: Sequence[UploadFile] | None,
        existing_step_images: Sequence[str] | None = None,
        delete_step_images: set[int] | None = None,
    ) -> None:
        """Пересобирает шаги и ингредиенты, сохраняя старые фото, если не выбрано новое."""
        recipe.steps.clear()
        recipe.ingredients.clear()

        images = list(step_images or [])
        existing_images = list(existing_step_images or [])
        delete_flags = delete_step_images or set()

        for idx, raw_instruction in enumerate(step_texts, start=1):
            instruction = (raw_instruction or "").strip()
            if not instruction:
                continue

            new_upload = images[idx - 1] if idx - 1 < len(images) else None
            existing_path = existing_images[idx - 1] if idx - 1 < len(existing_images) else None
            delete_requested = (idx - 1) in delete_flags

            image_path = None
            if delete_requested:
                image_path = None
            elif new_upload and getattr(new_upload, "filename", ""):
                image_path = await self.save_upload(new_upload)
            elif existing_path:
                image_path = existing_path

            recipe.steps.append(
                RecipeStep(
                    position=len(recipe.steps) + 1,
                    instruction=instruction,
                    image_path=image_path,
                )
            )

        for name, amount, unit in ingredients:
            recipe.ingredients.append(RecipeIngredient(name=name, amount=amount, unit=unit))

    def apply_tag_filter(self, query, selected_tags: list[str]):
        if not selected_tags:
            return query
        tag_array = cast(
            array(selected_tags, type_=ARRAY(Text())),
            ARRAY(Text()),
        )
        return query.where(cast(Recipe.tags, ARRAY(Text())).contains(tag_array))


RECIPE_TAGS = (
    RecipeTag(value="breakfast", label="Завтраки"),
    RecipeTag(value="lunch", label="Обеды"),
    RecipeTag(value="dinner", label="Ужины"),
)
PRIMARY_TAG_VALUES = ("breakfast", "lunch", "dinner")
PRIMARY_TAG_SET = set(PRIMARY_TAG_VALUES)

recipe_service = RecipeService(UPLOADS_DIR, RECIPE_TAGS)


async def fetch_extra_tag_models(session: AsyncSession, *, order_by_label: bool = True) -> list[RecipeExtraTag]:
    stmt = select(RecipeExtraTag)
    if order_by_label:
        stmt = stmt.order_by(RecipeExtraTag.label.asc())
    else:
        stmt = stmt.order_by(RecipeExtraTag.created_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


def serialize_extra_tags(extra_models: list[RecipeExtraTag]) -> list[dict[str, str]]:
    return [{"value": tag.value, "label": tag.label} for tag in extra_models]


def build_tag_labels(extra_models: list[RecipeExtraTag]) -> dict[str, str]:
    labels = dict(recipe_service.tag_labels)
    for tag in extra_models:
        labels[tag.value] = tag.label
    return labels


def resolve_back_url(request: Request, fallback: str) -> str:
    """Безопасно определяет URL для кнопки «Назад»."""
    referrer = request.headers.get("referer") or ""
    base_url = str(request.base_url)
    return referrer if referrer.startswith(base_url) else fallback


async def fetch_filtered_recipes(
    session: AsyncSession,
    selected_tags: list[str],
    search_query: str,
):
    """Возвращает список рецептов с учётом тегов и поискового запроса."""
    query = recipe_service.apply_tag_filter(
        recipe_service.base_query().order_by(Recipe.created_at.desc()),
        selected_tags,
    )
    if search_query:
        # Фильтруем по названию, описанию и ингредиентам через подзапрос.
        pattern = f"%{search_query.lower()}%"
        ingredient_ids_subq = select(RecipeIngredient.recipe_id).where(
            func.lower(RecipeIngredient.name).like(pattern)
        )
        query = query.where(
            or_(
                func.lower(Recipe.title).like(pattern),
                func.lower(Recipe.description).like(pattern),
                Recipe.id.in_(ingredient_ids_subq),
            )
        )
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/", response_class=HTMLResponse, name="recipes_list")
async def recipes_list(
    request: Request,
    q: str = Query("", max_length=120),
    tags: list[str] = Query([]),
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    """Список рецептов с фильтрацией по тегам."""
    extra_models = await fetch_extra_tag_models(session)
    extra_tags = serialize_extra_tags(extra_models)
    extra_tag_values = [tag["value"] for tag in extra_tags]
    selected_tags = recipe_service.normalize_tags(tags, extra_tag_values)
    search_query = (q or "").strip()
    recipes = await fetch_filtered_recipes(session, selected_tags, search_query)
    selected_extra_tags = [tag for tag in selected_tags if tag in extra_tag_values]
    primary_tags = [
        tag for tag in recipe_service.available_tags if tag["value"] in PRIMARY_TAG_SET
    ]
    tag_labels = build_tag_labels(extra_models)
    return templates.TemplateResponse(
        "recipes_list.html",
        {
            "request": request,
            "current_user": current_user,
            "recipes": recipes,
            "tag_labels": tag_labels,
            "primary_tags": primary_tags,
            "extra_tags": extra_tags,
            "extra_tag_values": extra_tag_values,
            "selected_extra_tags": selected_extra_tags,
            "selected_tags": selected_tags,
            "search_query": search_query,
        },
    )


@router.get("/search", response_class=JSONResponse, name="recipes_search")
async def recipes_search(
    request: Request,
    q: str = Query("", max_length=120),
    tags: list[str] = Query([]),
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    """AJAX-поиск рецептов для мгновенного обновления списка."""
    extra_models = await fetch_extra_tag_models(session)
    extra_tag_values = [tag.value for tag in extra_models]
    selected_tags = recipe_service.normalize_tags(tags, extra_tag_values)
    search_query = (q or "").strip()
    recipes = await fetch_filtered_recipes(session, selected_tags, search_query)
    tag_labels = build_tag_labels(extra_models)
    template = templates.get_template("partials/recipes_grid.html")
    html = template.render(
        {
            "request": request,
            "current_user": current_user,
            "recipes": recipes,
            "tag_labels": tag_labels,
        }
    )
    return {"html": html, "count": len(recipes)}


@router.get("/new", response_class=HTMLResponse, name="recipes_new")
async def new_recipe(
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    """Форма добавления нового рецепта."""
    referrer = request.headers.get("referer") or ""
    base_url = str(request.base_url)
    back_url = referrer if referrer.startswith(base_url) else str(request.url_for("recipes_list"))
    extra_models = await fetch_extra_tag_models(session)
    extra_tags = serialize_extra_tags(extra_models)
    primary_tags = [
        tag for tag in recipe_service.available_tags if tag["value"] in PRIMARY_TAG_SET
    ]
    return templates.TemplateResponse(
        "recipe_new.html",
        {
            "request": request,
            "current_user": current_user,
            "primary_tags": primary_tags,
            "extra_tags": extra_tags,
            "selected_tags": [],
            "selected_extra_tags": [],
            "previous_url": back_url,
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
    ingredient_units: list[str] = Form([]),
    tags: list[str] = Form([]),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
    cover_image: UploadFile | None = File(None),
    step_images: list[UploadFile] | None = File(None),
):
    """Создает рецепт и сохраняет шаги/ингредиенты."""
    step_texts = recipe_service.clean_steps(steps)
    ingredients = recipe_service.prepare_ingredients(ingredient_names, ingredient_amounts, ingredient_units)
    extra_models = await fetch_extra_tag_models(session)
    extra_tag_values = [tag.value for tag in extra_models]
    selected_tags = recipe_service.normalize_tags(tags, extra_tag_values)
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
    recipe_service.ensure_can_manage(recipe, current_user)
    fallback = str(request.url_for("recipe_detail", recipe_id=recipe.id))
    back_url = resolve_back_url(request, fallback)
    extra_models = await fetch_extra_tag_models(session)
    extra_tags = serialize_extra_tags(extra_models)
    extra_tag_values = [tag["value"] for tag in extra_tags]
    primary_tags = [
        tag for tag in recipe_service.available_tags if tag["value"] in PRIMARY_TAG_SET
    ]
    selected_tags = recipe.tags or []
    selected_extra_tags = [tag for tag in selected_tags if tag in extra_tag_values]
    return templates.TemplateResponse(
        "recipe_edit.html",
        {
            "request": request,
            "current_user": current_user,
            "recipe": recipe,
            "primary_tags": primary_tags,
            "extra_tags": extra_tags,
            "selected_tags": selected_tags,
            "selected_extra_tags": selected_extra_tags,
            "previous_url": back_url,
        },
    )


@router.post("/{recipe_id}/edit", response_class=HTMLResponse, name="update_recipe")
async def update_recipe(
    request: Request,
    recipe_id: int,
    title: str = Form(...),
    description: str = Form(""),
    steps: list[str] = Form(...),
    existing_step_images: list[str] = Form([]),
    delete_step_images: list[int] = Form([]),
    ingredient_names: list[str] = Form([]),
    ingredient_amounts: list[float] = Form([]),
    ingredient_units: list[str] = Form([]),
    tags: list[str] = Form([]),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
    cover_image: UploadFile | None = File(None),
    step_images: list[UploadFile] | None = File(None),
):
    """Обновляет рецепт: текст, шаги, ингредиенты, изображения."""
    recipe = await recipe_service.load_recipe(session, recipe_id)
    recipe_service.ensure_can_manage(recipe, current_user)

    cleaned_steps = recipe_service.clean_steps(steps)
    ingredients = recipe_service.prepare_ingredients(ingredient_names, ingredient_amounts, ingredient_units)
    extra_models = await fetch_extra_tag_models(session)
    extra_tag_values = [tag.value for tag in extra_models]
    selected_tags = recipe_service.normalize_tags(tags, extra_tag_values)
    recipe_service.validate_common_fields(title, cleaned_steps, ingredients)

    recipe.title = title.strip()
    recipe.description = description.strip() or None
    recipe.tags = selected_tags

    new_cover = await recipe_service.save_upload(cover_image)
    if new_cover:
        recipe.image_path = new_cover

    delete_flags = {int(idx) for idx in delete_step_images} if delete_step_images else set()
    await recipe_service.fill_recipe(
        recipe,
        cleaned_steps,
        ingredients,
        step_images,
        existing_step_images,
        delete_flags,
    )

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
    recipe_service.ensure_can_manage(recipe, current_user)
    await session.delete(recipe)
    await session.commit()
    return RedirectResponse(url="/recipes", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/view-mode", response_class=HTMLResponse, name="toggle_recipe_view")
async def toggle_recipe_view(
    request: Request,
    next_url: str = Form("/"),
):
    """Переключает режим минимального просмотра рецептов (с изображениями / без)."""
    current = bool(request.session.get("minimal_recipe_view"))
    request.session["minimal_recipe_view"] = not current
    return RedirectResponse(url=next_url or "/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/ingredients", response_class=JSONResponse, name="ingredients_suggest")
async def ingredient_suggest(
    q: str = Query("", min_length=1),
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    """Возвращает подсказки по ингредиентам (имя + единица) для автодополнения."""
    query = (
        select(RecipeIngredient.name, RecipeIngredient.unit)
        .where(func.lower(RecipeIngredient.name).like(f"%{q.lower()}%"))
        .limit(10)
    )
    result = await session.execute(query)
    rows = result.all()
    seen: set[str] = set()
    suggestions = []
    for name, unit in rows:
        key = (name or "").strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        suggestions.append({"name": key, "unit": unit or unit_converter.default_unit})
    return {"items": suggestions}


@router.get("/{recipe_id}", response_class=HTMLResponse, name="recipe_detail")
async def recipe_detail(
    request: Request,
    recipe_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    """Детальная страница рецепта."""
    recipe = await recipe_service.load_recipe(session, recipe_id)
    minimal_view = bool(request.session.get("minimal_recipe_view"))
    back_url = resolve_back_url(request, fallback=str(request.url_for("recipes_list")))
    extra_models = await fetch_extra_tag_models(session)
    tag_labels = build_tag_labels(extra_models)
    return templates.TemplateResponse(
        "recipe_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "recipe": recipe,
            "tag_labels": tag_labels,
            "minimal_view": minimal_view,
            "previous_url": back_url,
        },
    )
