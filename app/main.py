from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import STATIC_DIR, settings
from app.core.middleware import CSRFMiddleware, MultipartBodyLimitMiddleware, SecurityHeadersMiddleware
from app.db import base
from app.db.session import AsyncSessionLocal, engine
from app.routers import admin, auth, pages
from app.routers import recipes, profile
from app.services.ingredient_catalog import sync_catalog_from_recipe_ingredients

DEFAULT_EXTRA_TAGS = (
    ("snack", "Перекусы"),
    ("pp", "Полезное питание"),
    ("fast", "Быстрые блюда"),
    ("dessert", "Десерты"),
    ("soup", "Супы"),
)


def create_app() -> FastAPI:
    application = FastAPI()

    # FastAPI применяет middleware в обратном порядке добавления.
    # SessionMiddleware должен выполняться раньше CSRFMiddleware, чтобы был доступ к request.session.
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(CSRFMiddleware)
    application.add_middleware(MultipartBodyLimitMiddleware)
    application.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="fp_sess",
        same_site="lax",
        max_age=settings.session_max_age,
        https_only=False,
    )
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    application.include_router(pages.router)
    application.include_router(auth.router)
    application.include_router(recipes.router)
    application.include_router(profile.router)
    application.include_router(admin.router)

    @application.on_event("startup")
    async def on_startup() -> None:
        import app.models  # noqa: F401 регистрируем модели

        async with engine.begin() as conn:
            await conn.run_sync(base.Base.metadata.create_all)
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
            tag_count = await conn.scalar(text("SELECT COUNT(*) FROM recipe_extra_tags"))
            if not tag_count:
                for value, label in DEFAULT_EXTRA_TAGS:
                    await conn.execute(
                        text(
                            "INSERT INTO recipe_extra_tags (value, label) "
                            "VALUES (:value, :label) "
                            "ON CONFLICT DO NOTHING"
                        ),
                        {"value": value, "label": label},
                    )

        async with AsyncSessionLocal() as session:
            await sync_catalog_from_recipe_ingredients(session)
            await session.commit()

    return application


app = create_app()
