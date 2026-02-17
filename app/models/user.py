from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.recipe import Recipe
    from app.models.menu import Menu


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=expression.false(), default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, server_default=expression.false(), default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    recipes: Mapped[list["Recipe"]] = relationship(
        "Recipe",
        back_populates="author",
        cascade="all, delete-orphan",
    )
    menus: Mapped[list["Menu"]] = relationship(
        "Menu",
        back_populates="user",
        cascade="all, delete-orphan",
    )
