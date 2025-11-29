from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import TEMPLATES_DIR
from app.db.session import get_session
from app.dependencies.users import get_current_user, get_current_user_required
from app.models.recipe import Recipe
from app.models.menu import Menu, MenuDay, MenuMeal
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

MEAL_TYPES = [
    {"key": "breakfast", "label": "Завтрак"},
    {"key": "lunch", "label": "Обед"},
    {"key": "dinner", "label": "Ужин"},
]
MEAL_KEYS = {meal["key"] for meal in MEAL_TYPES}


def _parse_selection(values: list[str], recipe_ids: set[int]) -> dict[tuple[int, str], int]:
    parsed: dict[tuple[int, str], int] = {}
    for value in values:
        try:
            day_str, meal_key, recipe_str = value.split(":")
            day_number = int(day_str)
            recipe_id = int(recipe_str)
        except (ValueError, AttributeError):
            continue
        if meal_key not in MEAL_KEYS or recipe_id not in recipe_ids:
            continue
        parsed[(day_number, meal_key)] = recipe_id
    return parsed


def _split_recipes_by_meal(recipes: list[Recipe]) -> dict[str, list[Recipe]]:
    mapping: dict[str, list[Recipe]] = {meal["key"]: [] for meal in MEAL_TYPES}
    for recipe in recipes:
        recipe_tags = recipe.tags or []
        for meal_key in mapping:
            if meal_key in recipe_tags:
                mapping[meal_key].append(recipe)
    return mapping


def _build_menu(
    recipes: list[Recipe],
    grouped: dict[str, list[Recipe]],
    days: int,
    selection_map: dict[tuple[int, str], int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[int, str], int]]:
    recipe_by_id = {recipe.id: recipe for recipe in recipes}
    updated_selection: dict[tuple[int, str], int] = {}
    menu_plan: list[dict[str, Any]] = []
    shopping: dict[str, dict[str, float]] = {}

    for day in range(1, days + 1):
        meals: list[dict[str, Any]] = []
        for meal in MEAL_TYPES:
            key = (day, meal["key"])
            selected_recipe = None
            selected_id = selection_map.get(key)
            if selected_id is not None:
                selected_recipe = recipe_by_id.get(selected_id)

            candidates = grouped.get(meal["key"]) or recipes
            if not candidates:
                continue
            if selected_recipe is None:
                selected_recipe = random.choice(candidates)

            updated_selection[key] = selected_recipe.id
            meals.append({"meal": meal["label"], "meal_key": meal["key"], "recipe": selected_recipe})

            for ingredient in selected_recipe.ingredients:
                name = (ingredient.name or "").strip()
                if not name:
                    continue
                key_name = name.lower()
                entry = shopping.setdefault(key_name, {"name": name, "amount": 0.0})
                entry["amount"] += float(ingredient.amount or 0)

        menu_plan.append({"day": day, "meals": meals})

    shopping_list = sorted(shopping.values(), key=lambda item: item["name"])
    return menu_plan, shopping_list, updated_selection


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    categories = [
        {"key": "breakfast", "label": "Завтраки", "icon": "🍳"},
        {"key": "lunch", "label": "Обеды", "icon": "🍲"},
        {"key": "dinner", "label": "Ужины", "icon": "🍽"},
        {"key": "snacks", "label": "Перекусы", "icon": "🍪"},
        {"key": "pp", "label": "Полезное", "icon": "🥗"},
    ]

    weekly_menu = {
        "breakfast": "Тост с авокадо и яйцом",
        "lunch": "Томатный суп и сэндвич с индейкой",
        "dinner": "Запечённый лосось с овощами",
    }

    popular_recipes = [
        {
            "id": 1,
            "name": "Быстрая гранола с йогуртом",
            "type": "Завтрак",
            "pp": True,
            "time": "15 мин",
            "kcal": 320,
            "image_url": "https://via.placeholder.com/300x200?text=Breakfast",
        },
        {
            "id": 2,
            "name": "Кремовый тыквенный суп",
            "type": "Обед",
            "pp": True,
            "time": "30 мин",
            "kcal": 280,
            "image_url": "https://via.placeholder.com/300x200?text=Soup",
        },
        {
            "id": 3,
            "name": "Пряная куриная грудка",
            "type": "Ужин",
            "pp": True,
            "time": "25 мин",
            "kcal": 350,
            "image_url": "https://via.placeholder.com/300x200?text=Chicken",
        },
        {
            "id": 4,
            "name": "Энергетические конфеты",
            "type": "Перекус",
            "pp": True,
            "time": "5 мин",
            "kcal": 180,
            "image_url": "https://via.placeholder.com/300x200?text=Snack",
        },
    ]

    result = await session.execute(
        select(Recipe)
        .options(selectinload(Recipe.author))
        .order_by(Recipe.created_at.desc())
        .limit(3)
    )
    latest_recipes = result.scalars().all()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "categories": categories,
            "weekly_menu": weekly_menu,
            "popular_recipes": popular_recipes,
            "latest_recipes": latest_recipes,
            "current_user": current_user,
        },
    )


@router.get("/menu", response_class=HTMLResponse, name="menu_list")
async def menu_list(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    saved_menus: list[Menu] = []
    if current_user:
        result = await session.execute(
            select(Menu)
            .where(Menu.user_id == current_user.id)
            .order_by(Menu.created_at.desc())
        )
        saved_menus = result.scalars().all()

    return templates.TemplateResponse(
        "menu_list.html",
        {
            "request": request,
            "current_user": current_user,
            "saved_menus": saved_menus,
        },
    )


@router.get("/menu/new", response_class=HTMLResponse, name="menu_builder")
async def menu_builder(
    request: Request,
    days: int | None = Query(None, ge=1, le=7),
    selection: list[str] = Query([], alias="selection"),
    shuffle_day: int | None = Query(None),
    shuffle_meal: str | None = Query(None),
    set_day: int | None = Query(None),
    set_meal: str | None = Query(None),
    recipe_id: int | None = Query(None),
    menu_id: int | None = Query(None),
    current_user: User | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredients), selectinload(Recipe.author))
        .order_by(Recipe.created_at.desc())
    )
    recipes = result.scalars().all()
    recipe_ids = {recipe.id for recipe in recipes}
    grouped_recipes = _split_recipes_by_meal(recipes)

    selection_map = _parse_selection(selection, recipe_ids)

    if shuffle_day and shuffle_meal in MEAL_KEYS:
        selection_map.pop((shuffle_day, shuffle_meal), None)

    if (
        set_day
        and set_meal in MEAL_KEYS
        and recipe_id is not None
        and recipe_id in recipe_ids
    ):
        selection_map[(set_day, set_meal)] = recipe_id

    current_menu = None
    error_message: str | None = None

    if menu_id:
        if not current_user:
            error_message = "Войдите, чтобы открыть сохранённое меню."
        else:
            current_menu = await session.get(
                Menu,
                menu_id,
                options=(
                    selectinload(Menu.days)
                    .selectinload(MenuDay.meals)
                    .selectinload(MenuMeal.recipe),
                ),
            )
            if not current_menu or current_menu.user_id != current_user.id:
                error_message = "Меню не найдено или недоступно."
                current_menu = None
            else:
                stored_map: dict[tuple[int, str], int] = {}
                for day_obj in current_menu.days:
                    for meal_obj in day_obj.meals:
                        stored_map[(day_obj.day_number, meal_obj.meal_type)] = meal_obj.recipe_id
                stored_map.update(selection_map)
                selection_map = stored_map
                if not days:
                    days = current_menu.days_count

    menu_plan: list[dict[str, Any]] = []
    shopping_list: list[dict[str, Any]] = []

    if days:
        if not recipes:
            error_message = error_message or "Добавьте хотя бы один рецепт, чтобы построить меню."
        else:
            menu_plan, shopping_list, selection_map = _build_menu(
                recipes, grouped_recipes, days, selection_map
            )

    selection_values = [
        f"{day}:{meal}:{recipe_id}"
        for (day, meal), recipe_id in sorted(selection_map.items())
    ]

    return templates.TemplateResponse(
        "menu_builder.html",
        {
            "request": request,
            "current_user": current_user,
            "selected_days": days,
            "menu_plan": menu_plan,
            "shopping_list": shopping_list,
            "error_message": error_message,
            "has_recipes": bool(recipes),
            "selection_values": selection_values,
            "recipes_by_meal": grouped_recipes,
            "all_recipes": recipes,
            "current_menu": current_menu,
        },
    )


@router.post("/menu/save", response_class=HTMLResponse, name="save_menu")
async def save_menu(
    days: int = Form(..., ge=1, le=7),
    title: str = Form(...),
    selection: list[str] = Form([]),
    menu_id: int | None = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Укажите название меню.")

    result = await session.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .order_by(Recipe.created_at.desc())
    )
    recipes = result.scalars().all()
    if not recipes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет рецептов для сохранения меню.")

    recipe_ids = {recipe.id for recipe in recipes}
    selection_map = _parse_selection(selection, recipe_ids)
    grouped_recipes = _split_recipes_by_meal(recipes)
    menu_plan, _, selection_map = _build_menu(recipes, grouped_recipes, days, selection_map)

    if menu_id:
        menu = await session.get(Menu, menu_id)
        if not menu or menu.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Меню не найдено")
        menu.title = clean_title
        menu.days_count = days
        day_ids_subq = select(MenuDay.id).where(MenuDay.menu_id == menu.id)
        await session.execute(delete(MenuMeal).where(MenuMeal.day_id.in_(day_ids_subq)))
        await session.execute(delete(MenuDay).where(MenuDay.menu_id == menu.id))
    else:
        menu = Menu(title=clean_title, days_count=days, user=current_user)
        session.add(menu)
        await session.flush()

    for day in menu_plan:
        day_obj = MenuDay(day_number=day["day"], menu_id=menu.id)
        session.add(day_obj)
        await session.flush()
        for meal in day["meals"]:
            session.add(
                MenuMeal(day_id=day_obj.id, meal_type=meal["meal_key"], recipe_id=meal["recipe"].id)
            )

    await session.commit()
    return RedirectResponse(url="/menu", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/menu/{menu_id}/delete", response_class=HTMLResponse, name="delete_menu")
async def delete_menu(
    menu_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user_required),
):
    menu = await session.get(Menu, menu_id)
    if not menu or menu.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Меню не найдено")
    await session.delete(menu)
    await session.commit()
    return RedirectResponse(url="/menu", status_code=status.HTTP_303_SEE_OTHER)
