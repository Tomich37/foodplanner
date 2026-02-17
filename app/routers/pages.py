from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Sequence

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import TEMPLATES_DIR
from app.db.session import get_session
from app.dependencies.users import get_current_user, get_current_user_required
from app.models.menu import Menu, MenuDay, MenuMeal
from app.models.recipe import Recipe
from app.models.user import User
from app.services.cover_resolver import recipe_cover_resolver
from app.services.unit_converter import UnitConverter

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Глобальные helper'ы в шаблонах.
templates.env.globals["cover_url"] = recipe_cover_resolver.resolve
unit_converter = UnitConverter()
templates.env.globals["format_amount"] = unit_converter.format_human


@dataclass(frozen=True)
class MealType:
    """Описывает тип приема пищи с машинным ключом и русским названием."""

    key: str
    label: str


@dataclass
class MenuPlanResult:
    """Результат построения меню: план по дням, список покупок и выбор пользователя."""

    plan: list[dict[str, Any]]
    shopping_list: list[dict[str, Any]]
    selection_map: dict[tuple[int, str], int]


class MenuPlanner:
    """Инкапсулирует логику генерации меню (SRP) и позволяет расширять список приемов пищи (OCP)."""

    def __init__(self, meal_types: Sequence[MealType], unit_converter: UnitConverter):
        # Сохраняем доступные типы приемов пищи и готовим набор ключей для валидации ввода.
        self.meal_types: tuple[MealType, ...] = tuple(meal_types)
        self.meal_keys: set[str] = {meal.key for meal in meal_types}
        self.unit_converter = unit_converter

    def parse_selection(self, values: Sequence[str], recipe_ids: set[int]) -> dict[tuple[int, str], int]:
        """Разбирает выбор рецептов из строки запроса/формы и отбрасывает мусорные значения."""
        parsed: dict[tuple[int, str], int] = {}
        for value in values:
            try:
                day_str, meal_key, recipe_str = value.split(":")
                day_number = int(day_str)
                recipe_id = int(recipe_str)
            except (ValueError, AttributeError):
                # Если формат не совпадает, просто пропускаем запись, не ломая общий поток.
                continue
            if meal_key not in self.meal_keys or recipe_id not in recipe_ids:
                continue
            parsed[(day_number, meal_key)] = recipe_id
        return parsed

    def split_recipes_by_meal(self, recipes: Sequence[Recipe]) -> dict[str, list[Recipe]]:
        """Группирует рецепты по тегам приемов пищи для более точного выбора."""
        mapping: dict[str, list[Recipe]] = {meal.key: [] for meal in self.meal_types}
        for recipe in recipes:
            recipe_tags = recipe.tags or []
            for meal_key in mapping:
                if meal_key in recipe_tags:
                    mapping[meal_key].append(recipe)
        return mapping

    def build_menu(
        self,
        recipes: list[Recipe],
        grouped: dict[str, list[Recipe]],
        days: int,
        selection_map: dict[tuple[int, str], int],
    ) -> MenuPlanResult:
        """Формирует меню на заданное количество дней и собирает список покупок."""
        recipe_by_id = {recipe.id: recipe for recipe in recipes}
        updated_selection: dict[tuple[int, str], int] = {}
        menu_plan: list[dict[str, Any]] = []
        shopping: dict[str, dict[str, Any]] = {}

        for day in range(1, days + 1):
            meals: list[dict[str, Any]] = []
            for meal in self.meal_types:
                key = (day, meal.key)
                selected_recipe = recipe_by_id.get(selection_map.get(key, 0))

                candidates = grouped.get(meal.key) or recipes
                if not candidates:
                    continue
                if selected_recipe is None:
                    # Если пользователь не выбрал рецепт – подставляем случайный подходящий вариант.
                    selected_recipe = random.choice(candidates)

                updated_selection[key] = selected_recipe.id
                meals.append({"meal": meal.label, "meal_key": meal.key, "recipe": selected_recipe})

                # Накопление ингредиентов для списка покупок.
            for ingredient in selected_recipe.ingredients:
                name = (ingredient.name or "").strip()
                if not name:
                    continue
                key_name = name.lower()
                entry = shopping.setdefault(
                    key_name,
                    {"name": name, "mass": 0.0, "volume": 0.0, "other": False},
                )
                base_amount, unit_type = self.unit_converter.to_base(
                    float(ingredient.amount or 0), getattr(ingredient, "unit", None)
                )
                if unit_type == "mass" and base_amount:
                    entry["mass"] += base_amount
                elif unit_type == "volume" and base_amount:
                    entry["volume"] += base_amount
                else:
                    entry["other"] = True

            menu_plan.append({"day": day, "meals": meals})

        shopping_list: list[dict[str, Any]] = []
        for item in shopping.values():
            display = "по вкусу" if item.get("other") else ""
            if item.get("mass", 0) > 0:
                value, label = self.unit_converter.format_total(item["mass"], "mass")
                display = f"{value:.2f} {label}"
            elif item.get("volume", 0) > 0:
                value, label = self.unit_converter.format_total(item["volume"], "volume")
                display = f"{value:.2f} {label}"
            if not display:
                display = "—"
            shopping_list.append({"name": item["name"], "display": display})

        shopping_list = sorted(shopping_list, key=lambda item: item["name"])
        return MenuPlanResult(plan=menu_plan, shopping_list=shopping_list, selection_map=updated_selection)

    @staticmethod
    def selection_from_menu(menu: Menu) -> dict[tuple[int, str], int]:
        """Извлекает из сохраненного меню выбор рецептов в виде словаря для дальнейшей работы."""
        mapping: dict[tuple[int, str], int] = {}
        for day_obj in menu.days:
            for meal_obj in day_obj.meals:
                mapping[(day_obj.day_number, meal_obj.meal_type)] = meal_obj.recipe_id
        return mapping


MEAL_TYPES = (
    MealType(key="breakfast", label="Завтрак"),
    MealType(key="lunch", label="Обед"),
    MealType(key="dinner", label="Ужин"),
)
menu_planner = MenuPlanner(MEAL_TYPES, unit_converter)


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Главная страница с подборками и последними рецептами."""
    # Статичные категории для быстрого перехода по основным разделам.
    categories = [
        {"key": "breakfast", "label": "Завтраки", "icon": "\U0001F963"},
        {"key": "lunch", "label": "Обеды", "icon": "\U0001F372"},
        {"key": "dinner", "label": "Ужины", "icon": "\U0001F37D"},
    ]

    # Пример недельного меню для демонстрации возможностей сервиса.
    weekly_menu = {
        "breakfast": "Овсянка с ягодами и орехами",
        "lunch": "Куриный суп с овощами и лапшой",
        "dinner": "Запеченная рыба с картофелем",
    }

    # Забираем последние рецепты из базы для блока «новинки».
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
    """Страница со списком сохраненных меню пользователя."""
    saved_menus: list[Menu] = []
    if current_user:
        # Показываем меню конкретного пользователя в порядке убывания даты создания.
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
    """Конструктор меню: выбор рецептов, перетасовка и загрузка сохраненных меню."""
    # Грузим все рецепты с ингредиентами и автором, чтобы сразу использовать их в конструкторе.
    result = await session.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredients), selectinload(Recipe.author))
        .order_by(Recipe.created_at.desc())
    )
    recipes = result.scalars().all()
    recipe_ids = {recipe.id for recipe in recipes}
    grouped_recipes = menu_planner.split_recipes_by_meal(recipes)

    # Разбираем текущие выборы пользователя из query-параметров.
    selection_map = menu_planner.parse_selection(selection, recipe_ids)

    # Если нужно «перемешать» конкретный прием пищи, убираем сохраненный выбор.
    if shuffle_day and shuffle_meal in menu_planner.meal_keys:
        selection_map.pop((shuffle_day, shuffle_meal), None)

    # Принудительная установка выбранного рецепта.
    if (
        set_day
        and set_meal in menu_planner.meal_keys
        and recipe_id is not None
        and recipe_id in recipe_ids
    ):
        selection_map[(set_day, set_meal)] = recipe_id

    current_menu = None
    error_message: str | None = None

    if menu_id:
        if not current_user:
            error_message = "Нужна авторизация, чтобы открыть сохранённое меню."
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
                # Подмешиваем сохраненный выбор к текущему состоянию конструктора.
                stored_map = menu_planner.selection_from_menu(current_menu)
                stored_map.update(selection_map)
                selection_map = stored_map
                if not days:
                    days = current_menu.days_count

    menu_plan_result: MenuPlanResult | None = None

    if days:
        if not recipes:
            error_message = error_message or "Рецептов пока нет, составить меню невозможно."
        else:
            menu_plan_result = menu_planner.build_menu(
                recipes, grouped_recipes, days, selection_map
            )
            selection_map = menu_plan_result.selection_map

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
            "menu_plan": menu_plan_result.plan if menu_plan_result else [],
            "shopping_list": menu_plan_result.shopping_list if menu_plan_result else [],
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
    """Сохраняет меню пользователя и обновляет записи в базе."""
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Название меню не может быть пустым.")

    # Подгружаем рецепты вместе с ингредиентами для корректного построения меню.
    result = await session.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .order_by(Recipe.created_at.desc())
    )
    recipes = result.scalars().all()
    if not recipes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет рецептов для составления меню.")

    recipe_ids = {recipe.id for recipe in recipes}
    selection_map = menu_planner.parse_selection(selection, recipe_ids)
    grouped_recipes = menu_planner.split_recipes_by_meal(recipes)
    menu_plan_result = menu_planner.build_menu(recipes, grouped_recipes, days, selection_map)

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

    for day in menu_plan_result.plan:
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
    """Удаляет сохраненное меню, если оно принадлежит текущему пользователю."""
    menu = await session.get(Menu, menu_id)
    if not menu or menu.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Меню не найдено")
    await session.delete(menu)
    await session.commit()
    return RedirectResponse(url="/menu", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users/{user_id}", response_class=HTMLResponse, name="user_profile")
async def user_profile(
    request: Request,
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    """Публичная страница пользователя со статистикой и списком его рецептов."""
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.recipes).selectinload(Recipe.author),
            selectinload(User.recipes).selectinload(Recipe.steps),
            selectinload(User.recipes).selectinload(Recipe.ingredients),
            selectinload(User.menus),
        )
    )
    profile_user = result.scalar_one_or_none()
    if not profile_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    recipes = sorted(profile_user.recipes, key=lambda r: r.created_at or 0, reverse=True)
    stats = {
        "total_recipes": len(recipes),
        "admin": profile_user.is_admin,
        "joined": profile_user.created_at,
    }

    return templates.TemplateResponse(
        "user_profile.html",
        {
            "request": request,
            "current_user": current_user,
            "profile_user": profile_user,
            "recipes": recipes,
            "stats": stats,
            "is_self": current_user.id == profile_user.id if current_user else False,
        },
    )
