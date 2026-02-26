from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import STATIC_DIR, settings
from app.core.middleware import CSRFMiddleware, MultipartBodyLimitMiddleware, SecurityHeadersMiddleware
from app.db.bootstrap import bootstrap_database
from app.db.session import AsyncSessionLocal, engine
from app.routers import admin, auth, pages, profile, recipes
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
    # SessionMiddleware должен выполняться раньше CSRFMiddleware,
    # чтобы в CSRF-проверке уже была доступна request.session.
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
        await bootstrap_database(engine, default_extra_tags=DEFAULT_EXTRA_TAGS)

        async with AsyncSessionLocal() as session:
            await sync_catalog_from_recipe_ingredients(session)
            await session.commit()

    return application


app = create_app()
