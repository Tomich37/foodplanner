from fastapi import APIRouter, Depends, Request
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


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    categories = [
        {"key": "breakfast", "label": "Завтраки", "icon": "BF"},
        {"key": "lunch", "label": "Обеды", "icon": "LN"},
        {"key": "dinner", "label": "Ужины", "icon": "DN"},
        {"key": "snacks", "label": "Перекусы", "icon": "SN"},
        {"key": "pp", "label": "Полезное", "icon": "PP"},
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
