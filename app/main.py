from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import STATIC_DIR, settings
from app.db import base
from app.db.session import engine
from app.routers import admin, auth, pages
from app.routers import recipes, profile


def create_app() -> FastAPI:
    application = FastAPI()

    application.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="fp_sess")
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    application.include_router(pages.router)
    application.include_router(auth.router)
    application.include_router(recipes.router)
    application.include_router(profile.router)
    application.include_router(admin.router)

    @application.on_event("startup")
    async def on_startup() -> None:
        import app.models  # noqa: F401 ensures models registered

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
                    "ALTER TABLE IF EXISTS recipe_ingredients "
                    "ADD COLUMN IF NOT EXISTS unit VARCHAR(16) NOT NULL DEFAULT 'g'"
                )
            )

    return application


app = create_app()
