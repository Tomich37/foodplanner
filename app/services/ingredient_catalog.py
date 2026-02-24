from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngredientAlias, IngredientCanonical, RecipeIngredient

_ADJECTIVE_SUFFIXES = (
    "ий",
    "ый",
    "ой",
    "ая",
    "ое",
    "ее",
    "ые",
    "ие",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ом",
    "ым",
    "ых",
    "их",
    "ую",
    "юю",
    "яя",
)


@dataclass(frozen=True)
class CatalogSyncStats:
    created_canonicals: int = 0
    created_aliases: int = 0


def normalize_ingredient_name(value: str) -> str:
    cleaned = (value or "").strip().lower().replace("ё", "е")
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    for separator in (",", ";", "/"):
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0]
    cleaned = re.sub(r"[^0-9a-zа-я\s-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _looks_like_adjective(token: str) -> bool:
    return len(token) > 2 and token.endswith(_ADJECTIVE_SUFFIXES)


def derive_canonical_key(normalized_alias: str) -> str:
    tokens = normalized_alias.split()
    if len(tokens) > 1 and all(_looks_like_adjective(token) for token in tokens[1:]):
        return tokens[0]
    return normalized_alias


def canonical_name_for_value(value: str, alias_map: dict[str, str] | None = None) -> str:
    normalized_alias = normalize_ingredient_name(value)
    if not normalized_alias:
        return ""
    if alias_map:
        known = alias_map.get(normalized_alias)
        if known:
            return known
    return derive_canonical_key(normalized_alias)


async def fetch_ingredient_alias_map(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(
        select(IngredientAlias.normalized_alias, IngredientCanonical.name).join(
            IngredientCanonical, IngredientCanonical.id == IngredientAlias.canonical_id
        )
    )
    rows = result.all()
    return {normalized_alias: canonical_name for normalized_alias, canonical_name in rows if normalized_alias and canonical_name}


async def get_or_create_canonical(
    session: AsyncSession,
    raw_name: str,
    *,
    display_name: str | None = None,
) -> IngredientCanonical | None:
    normalized_name = normalize_ingredient_name(raw_name)
    if not normalized_name:
        return None
    existing_result = await session.execute(
        select(IngredientCanonical).where(IngredientCanonical.normalized_name == normalized_name)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return existing
    canonical = IngredientCanonical(
        name=(display_name or normalized_name).strip() or normalized_name,
        normalized_name=normalized_name,
    )
    session.add(canonical)
    await session.flush()
    return canonical


async def attach_aliases_to_canonical(
    session: AsyncSession,
    canonical: IngredientCanonical,
    aliases: Iterable[str],
    *,
    overwrite_existing: bool = False,
) -> tuple[int, list[str]]:
    normalized_to_alias: dict[str, str] = {}
    for value in aliases:
        raw = (value or "").strip()
        normalized = normalize_ingredient_name(raw)
        if not raw or not normalized:
            continue
        normalized_to_alias.setdefault(normalized, raw)
    if not normalized_to_alias:
        return 0, []

    result = await session.execute(
        select(IngredientAlias).where(IngredientAlias.normalized_alias.in_(tuple(normalized_to_alias)))
    )
    existing_aliases = {row.normalized_alias: row for row in result.scalars().all()}

    created = 0
    conflicts: list[str] = []
    for normalized, raw in normalized_to_alias.items():
        existing = existing_aliases.get(normalized)
        if existing:
            if existing.canonical_id == canonical.id:
                continue
            if overwrite_existing:
                existing.canonical_id = canonical.id
                existing.alias = raw
                continue
            conflicts.append(raw)
            continue
        session.add(
            IngredientAlias(
                canonical_id=canonical.id,
                alias=raw,
                normalized_alias=normalized,
            )
        )
        created += 1
    return created, conflicts


async def sync_ingredient_catalog(session: AsyncSession, names: Iterable[str]) -> CatalogSyncStats:
    normalized_to_raw: dict[str, str] = {}
    for value in names:
        raw = (value or "").strip()
        normalized = normalize_ingredient_name(raw)
        if not raw or not normalized:
            continue
        normalized_to_raw.setdefault(normalized, raw)
    if not normalized_to_raw:
        return CatalogSyncStats()

    alias_keys = tuple(normalized_to_raw)
    result = await session.execute(
        select(IngredientAlias.normalized_alias).where(IngredientAlias.normalized_alias.in_(alias_keys))
    )
    existing_alias_keys = {normalized_alias for (normalized_alias,) in result.all()}

    missing_alias_keys = [key for key in alias_keys if key not in existing_alias_keys]
    if not missing_alias_keys:
        return CatalogSyncStats()

    canonical_keys: set[str] = set()
    for alias_key in missing_alias_keys:
        canonical_key = derive_canonical_key(alias_key)
        if canonical_key:
            canonical_keys.add(canonical_key)
    canonical_result = await session.execute(
        select(IngredientCanonical).where(IngredientCanonical.normalized_name.in_(tuple(canonical_keys)))
    )
    canonical_by_key = {item.normalized_name: item for item in canonical_result.scalars().all()}

    created_canonicals = 0
    for canonical_key in sorted(canonical_keys):
        if canonical_key in canonical_by_key:
            continue
        canonical = IngredientCanonical(name=canonical_key, normalized_name=canonical_key)
        session.add(canonical)
        canonical_by_key[canonical_key] = canonical
        created_canonicals += 1
    if created_canonicals:
        await session.flush()

    created_aliases = 0
    for alias_key in missing_alias_keys:
        canonical_key = derive_canonical_key(alias_key)
        canonical = canonical_by_key.get(canonical_key)
        if not canonical:
            continue
        session.add(
            IngredientAlias(
                canonical_id=canonical.id,
                alias=normalized_to_raw[alias_key],
                normalized_alias=alias_key,
            )
        )
        created_aliases += 1

    return CatalogSyncStats(created_canonicals=created_canonicals, created_aliases=created_aliases)


async def sync_catalog_from_recipe_ingredients(session: AsyncSession) -> CatalogSyncStats:
    result = await session.execute(select(RecipeIngredient.name).distinct())
    names = [name for (name,) in result.all() if name]
    return await sync_ingredient_catalog(session, names)
