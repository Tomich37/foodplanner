
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User

class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    days_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="menus")
    days: Mapped[list["MenuDay"]] = relationship(
        "MenuDay", back_populates="menu", cascade="all, delete-orphan", order_by="MenuDay.day_number"
    )


class MenuDay(Base):
    __tablename__ = "menu_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id", ondelete="CASCADE"))
    day_number: Mapped[int] = mapped_column(Integer)

    menu: Mapped["Menu"] = relationship("Menu", back_populates="days")
    meals: Mapped[list["MenuMeal"]] = relationship(
        "MenuMeal", back_populates="day", cascade="all, delete-orphan", order_by="MenuMeal.id"
    )


class MenuMeal(Base):
    __tablename__ = "menu_meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("menu_days.id", ondelete="CASCADE"))
    meal_type: Mapped[str] = mapped_column(String(32))
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))

    day: Mapped["MenuDay"] = relationship("MenuDay", back_populates="meals")
    recipe: Mapped["Recipe"] = relationship("Recipe")
