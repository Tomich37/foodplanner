from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TEMPLATES_DIR
from app.core.security import hash_password, verify_password
from app.db.session import get_session
from app.dependencies.users import get_current_user
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/register", response_class=HTMLResponse, name="register_form")
async def register_form(
    request: Request, current_user: User | None = Depends(get_current_user)
):
    if current_user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "register.html",
        {"request": request, "current_user": current_user, "errors": None},
    )


@router.post("/register", response_class=HTMLResponse)
async def register_user(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    errors: list[str] = []
    email_normalized = email.strip().lower()

    if password != confirm_password:
        errors.append("Пароли не совпадают.")

    result = await session.execute(select(User).where(User.email == email_normalized))
    if result.scalar_one_or_none():
        errors.append("Пользователь с таким e-mail уже существует.")

    if errors:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "errors": errors,
                "current_user": None,
                "form_email": email,
                "form_full_name": full_name,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = User(
        email=email_normalized,
        full_name=full_name.strip() or None,
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.flush()
    await session.commit()
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse, name="login_form")
async def login_form(
    request: Request, current_user: User | None = Depends(get_current_user)
):
    if current_user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "current_user": current_user, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(User).where(User.email == email.strip().lower())
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Неверный e-mail или пароль.",
                "current_user": None,
                "form_email": email,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout", name="logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
