from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import STATIC_DIR, settings
from app.db import base
from app.db.session import engine
from app.routers import auth, pages
from app.routers import recipes


def create_app() -> FastAPI:
    application = FastAPI()

    application.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="fp_sess")
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    application.include_router(pages.router)
    application.include_router(auth.router)
    application.include_router(recipes.router)

    @application.on_event("startup")
    async def on_startup() -> None:
        import app.models  # noqa: F401 ensures models registered

        async with engine.begin() as conn:
            await conn.run_sync(base.Base.metadata.create_all)

    return application


app = create_app()
