from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import TEMPLATES_DIR
from app.db.session import get_session
from app.dependencies.users import get_current_user
from app.models import Recipe
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

MEAL_TYPES = [
    {"key": "breakfast", "label": "Завтрак"},
    {"key": "lunch", "label": "Обед"},
    {"key": "dinner", "label": "Ужин"},
]


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
            meals.append(
                {"meal": meal["label"], "meal_key": meal["key"], "recipe": selected_recipe}
            )

            for ingredient in selected_recipe.ingredients:
                name = (ingredient.name or "").strip()
                if not name:
                    continue
                key = name.lower()
                entry = shopping.setdefault(key, {"name": name, "amount": 0.0})
                entry["amount"] += float(ingredient.amount or 0)

        menu_plan.append({"day": day, "meals": meals})

    shopping_list = sorted(shopping.values(), key=lambda item: item["name"])
    return menu_plan, shopping_list, updated_selection


@router.get("/menu", response_class=HTMLResponse, name="menu_builder")
async def menu_builder(
    request: Request,
    days: int | None = Query(None, ge=1, le=7),
    selection: list[str] = Query([], alias="selection"),
    shuffle_day: int | None = Query(None),
    shuffle_meal: str | None = Query(None),
    set_day: int | None = Query(None),
    set_meal: str | None = Query(None),
    recipe_id: int | None = Query(None),
    current_user: User | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredients), selectinload(Recipe.author))
        .order_by(Recipe.created_at.desc())
    )
    recipes = result.scalars().all()
    recipe_by_id = {recipe.id: recipe for recipe in recipes}
    grouped_recipes = _split_recipes_by_meal(recipes)
    meal_keys = {meal["key"] for meal in MEAL_TYPES}

    selection_map: dict[tuple[int, str], int] = {}
    for value in selection:
        try:
            day_str, meal_key, recipe_str = value.split(":")
            parsed_day = int(day_str)
            parsed_recipe = int(recipe_str)
        except (ValueError, AttributeError):
            continue
        if meal_key not in meal_keys or parsed_recipe not in recipe_by_id:
            continue
        selection_map[(parsed_day, meal_key)] = parsed_recipe

    if shuffle_day and shuffle_meal in meal_keys:
        selection_map.pop((shuffle_day, shuffle_meal), None)

    if (
        set_day
        and set_meal in meal_keys
        and recipe_id is not None
        and recipe_id in recipe_by_id
    ):
        selection_map[(set_day, set_meal)] = recipe_id

    menu_plan: list[dict[str, Any]] = []
    shopping_list: list[dict[str, Any]] = []
    error_message: str | None = None

    if days:
        if not recipes:
            error_message = "Пока нет рецептов для генерации меню."
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
        },
    )
