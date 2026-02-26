from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection

from app.db import base


async def _apply_legacy_updates(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS recipes "
            "ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}'::text[]"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS users "
            "ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS users "
            "ADD COLUMN IF NOT EXISTS is_banned BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS recipe_ingredients "
            "ADD COLUMN IF NOT EXISTS unit VARCHAR(16) NOT NULL DEFAULT 'g'"
        )
    )


async def _apply_manual_price_columns(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS ingredient_catalog "
            "ADD COLUMN IF NOT EXISTS current_price_rub NUMERIC(12,2)"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS ingredient_catalog "
            "ADD COLUMN IF NOT EXISTS current_price_unit VARCHAR(8)"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS ingredient_catalog "
            "ADD COLUMN IF NOT EXISTS current_price_currency VARCHAR(3) NOT NULL DEFAULT 'RUB'"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS ingredient_catalog "
            "ADD COLUMN IF NOT EXISTS current_price_region VARCHAR(32) NOT NULL DEFAULT 'RU_AVG'"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS ingredient_catalog "
            "ADD COLUMN IF NOT EXISTS current_price_source VARCHAR(64)"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS ingredient_catalog "
            "ADD COLUMN IF NOT EXISTS current_price_updated_at TIMESTAMPTZ"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE IF EXISTS ingredient_catalog "
            "ADD COLUMN IF NOT EXISTS price_is_stale BOOLEAN NOT NULL DEFAULT TRUE"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_ingredient_catalog_price_updated_at "
            "ON ingredient_catalog (current_price_updated_at DESC)"
        )
    )


async def _remove_price_worker_artifacts(conn: AsyncConnection) -> None:
    # Сервис авто-парсинга цен удален, поэтому служебные таблицы больше не нужны.
    await conn.execute(text("DROP TABLE IF EXISTS ingredient_price_snapshots"))
    await conn.execute(text("DROP TABLE IF EXISTS ingredient_price_runs"))
    await conn.execute(text("DROP TABLE IF EXISTS price_source_state"))


async def _seed_default_tags(conn: AsyncConnection, tags: Sequence[tuple[str, str]]) -> None:
    if not tags:
        return
    tag_count = await conn.scalar(text("SELECT COUNT(*) FROM recipe_extra_tags"))
    if tag_count:
        return
    for value, label in tags:
        await conn.execute(
            text(
                "INSERT INTO recipe_extra_tags (value, label) "
                "VALUES (:value, :label) "
                "ON CONFLICT DO NOTHING"
            ),
            {"value": value, "label": label},
        )


async def bootstrap_database(engine: AsyncEngine, *, default_extra_tags: Sequence[tuple[str, str]] = ()) -> None:
    import app.models  # noqa: F401 Регистрируем SQLAlchemy-модели перед create_all.

    async with engine.begin() as conn:
        await conn.run_sync(base.Base.metadata.create_all)
        await _apply_legacy_updates(conn)
        await _apply_manual_price_columns(conn)
        await _remove_price_worker_artifacts(conn)
        await _seed_default_tags(conn, default_extra_tags)
