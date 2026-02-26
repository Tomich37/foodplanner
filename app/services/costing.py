from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngredientAlias, IngredientCanonical
from app.services.unit_converter import UnitConverter, UnitType

if TYPE_CHECKING:
    from app.models.recipe import Recipe

_MONEY_STEP = Decimal("0.01")


@dataclass(frozen=True)
class PriceReference:
    price_rub: Decimal
    unit: str
    unit_type: UnitType


@dataclass(frozen=True)
class RecipeCostSummary:
    total_rub: Decimal | None
    priced_ingredients: int
    total_ingredients: int
    missing_ingredients: int
    is_complete: bool


@dataclass(frozen=True)
class MenuCostSummary:
    total_rub: Decimal | None
    total_meals: int
    meals_with_price: int
    complete_meals: int
    is_complete: bool


def _to_money(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(_MONEY_STEP, rounding=ROUND_HALF_UP)


def _price_unit_to_type(unit: str | None) -> UnitType | None:
    if unit == "kg":
        return "mass"
    if unit == "l":
        return "volume"
    if unit == "pcs":
        return "count"
    return None


def _normalize_for_lookup(value: str) -> str:
    cleaned = (value or "").strip().lower().replace("\u0451", "\u0435")
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    for separator in (",", ";", "/"):
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0]
    cleaned = re.sub("[^0-9a-z\u0430-\u044f\\s-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def format_rub(value: Decimal | float | int | None) -> str:
    if value is None:
        return "-"
    amount = _to_money(value)
    return f"{amount:.2f}".replace(".", ",") + " \u0440\u0443\u0431."


async def build_price_lookup(session: AsyncSession) -> dict[str, PriceReference]:
    lookup: dict[str, PriceReference] = {}

    rows = await session.execute(
        select(
            IngredientAlias.normalized_alias,
            IngredientAlias.alias,
            IngredientCanonical.normalized_name,
            IngredientCanonical.name,
            IngredientCanonical.current_price_rub,
            IngredientCanonical.current_price_unit,
        )
        .join(IngredientCanonical, IngredientCanonical.id == IngredientAlias.canonical_id)
        .where(
            IngredientCanonical.current_price_rub.is_not(None),
            IngredientCanonical.current_price_unit.is_not(None),
            IngredientCanonical.current_price_currency == "RUB",
            IngredientCanonical.price_is_stale.is_(False),
        )
    )

    for normalized_alias, alias, normalized_name, canonical_name, price_rub, unit in rows.all():
        unit_type = _price_unit_to_type(unit)
        if price_rub is None or unit_type is None:
            continue
        reference = PriceReference(
            price_rub=Decimal(str(price_rub)),
            unit=unit,
            unit_type=unit_type,
        )
        for key in {
            normalized_alias or "",
            normalized_name or "",
            _normalize_for_lookup(alias or ""),
            _normalize_for_lookup(canonical_name or ""),
        }:
            if key:
                lookup[key] = reference

    canonical_rows = await session.execute(
        select(
            IngredientCanonical.normalized_name,
            IngredientCanonical.name,
            IngredientCanonical.current_price_rub,
            IngredientCanonical.current_price_unit,
        ).where(
            IngredientCanonical.current_price_rub.is_not(None),
            IngredientCanonical.current_price_unit.is_not(None),
            IngredientCanonical.current_price_currency == "RUB",
            IngredientCanonical.price_is_stale.is_(False),
        )
    )

    for normalized_name, canonical_name, price_rub, unit in canonical_rows.all():
        unit_type = _price_unit_to_type(unit)
        if price_rub is None or unit_type is None:
            continue
        reference = PriceReference(
            price_rub=Decimal(str(price_rub)),
            unit=unit,
            unit_type=unit_type,
        )
        for key in {
            normalized_name or "",
            _normalize_for_lookup(canonical_name or ""),
        }:
            if key:
                lookup.setdefault(key, reference)

    return lookup


def calculate_recipe_cost(
    recipe: Recipe,
    price_lookup: Mapping[str, PriceReference],
    unit_converter: UnitConverter,
) -> RecipeCostSummary:
    ingredients = list(getattr(recipe, "ingredients", []) or [])
    total_ingredients = len(ingredients)
    if total_ingredients == 0:
        return RecipeCostSummary(
            total_rub=None,
            priced_ingredients=0,
            total_ingredients=0,
            missing_ingredients=0,
            is_complete=False,
        )

    total_rub = Decimal("0")
    priced_ingredients = 0

    for ingredient in ingredients:
        normalized_name = _normalize_for_lookup(getattr(ingredient, "name", ""))
        if not normalized_name:
            continue
        reference = price_lookup.get(normalized_name)
        if reference is None:
            continue

        amount_raw = getattr(ingredient, "amount", 0)
        try:
            amount = float(amount_raw or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue

        base_amount, unit_type = unit_converter.to_base(amount, getattr(ingredient, "unit", "g"))
        if base_amount is None or unit_type != reference.unit_type:
            continue

        base_amount_dec = Decimal(str(base_amount))
        if reference.unit in {"kg", "l"}:
            ingredient_cost = (base_amount_dec / Decimal("1000")) * reference.price_rub
        elif reference.unit == "pcs":
            ingredient_cost = base_amount_dec * reference.price_rub
        else:
            continue

        total_rub += ingredient_cost
        priced_ingredients += 1

    total_rub_value = _to_money(total_rub) if priced_ingredients > 0 else None
    missing_ingredients = max(total_ingredients - priced_ingredients, 0)
    return RecipeCostSummary(
        total_rub=total_rub_value,
        priced_ingredients=priced_ingredients,
        total_ingredients=total_ingredients,
        missing_ingredients=missing_ingredients,
        is_complete=total_ingredients > 0 and missing_ingredients == 0,
    )


def build_recipe_cost_map(
    recipes: Sequence[Recipe],
    price_lookup: Mapping[str, PriceReference],
    unit_converter: UnitConverter,
) -> dict[int, RecipeCostSummary]:
    result: dict[int, RecipeCostSummary] = {}
    for recipe in recipes:
        recipe_id = getattr(recipe, "id", None)
        if recipe_id is None:
            continue
        result[recipe_id] = calculate_recipe_cost(recipe, price_lookup, unit_converter)
    return result


def calculate_menu_cost(
    menu_plan: Sequence[dict[str, Any]],
    recipe_costs: Mapping[int, RecipeCostSummary],
) -> MenuCostSummary:
    total_rub = Decimal("0")
    total_meals = 0
    meals_with_price = 0
    complete_meals = 0

    for day in menu_plan:
        meals = day.get("meals", []) if isinstance(day, dict) else []
        for meal in meals:
            if not isinstance(meal, dict):
                continue
            recipe = meal.get("recipe")
            if recipe is None:
                continue
            recipe_id = getattr(recipe, "id", None)
            if recipe_id is None:
                continue
            total_meals += 1
            summary = recipe_costs.get(recipe_id)
            if summary is None or summary.total_rub is None:
                continue
            meals_with_price += 1
            total_rub += summary.total_rub
            if summary.is_complete:
                complete_meals += 1

    return MenuCostSummary(
        total_rub=_to_money(total_rub) if meals_with_price > 0 else None,
        total_meals=total_meals,
        meals_with_price=meals_with_price,
        complete_meals=complete_meals,
        is_complete=total_meals > 0 and complete_meals == total_meals,
    )

