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


def _build_menu(recipes: list[Recipe], days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped = _split_recipes_by_meal(recipes)
    menu_plan: list[dict[str, Any]] = []
    shopping: dict[str, dict[str, float]] = {}

    for day in range(1, days + 1):
        meals: list[dict[str, Any]] = []
        for meal in MEAL_TYPES:
            candidates = grouped[meal["key"]] or recipes
            if not candidates:
                continue
            recipe = random.choice(candidates)
            meals.append({"meal": meal["label"], "recipe": recipe})

            for ingredient in recipe.ingredients:
                name = (ingredient.name or "").strip()
                if not name:
                    continue
                key = name.lower()
                entry = shopping.setdefault(key, {"name": name, "amount": 0.0})
                entry["amount"] += float(ingredient.amount or 0)

        menu_plan.append({"day": day, "meals": meals})

    shopping_list = sorted(shopping.values(), key=lambda item: item["name"])
    return menu_plan, shopping_list


@router.get("/menu", response_class=HTMLResponse, name="menu_builder")
async def menu_builder(
    request: Request,
    days: int | None = Query(None, ge=1, le=7),
    current_user: User | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredients), selectinload(Recipe.author))
        .order_by(Recipe.created_at.desc())
    )
    recipes = result.scalars().all()

    menu_plan: list[dict[str, Any]] = []
    shopping_list: list[dict[str, Any]] = []
    error_message: str | None = None

    if days:
        if not recipes:
            error_message = "Пока нет рецептов для генерации меню."
        else:
            menu_plan, shopping_list = _build_menu(recipes, days)

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
        },
    )
