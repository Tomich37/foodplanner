from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text())
    image_path: Mapped[Optional[str]] = mapped_column(String(512))
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), server_default="{}", default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    author: Mapped["User"] = relationship("User", back_populates="recipes")
    steps: Mapped[list["RecipeStep"]] = relationship(
        "RecipeStep",
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeStep.position",
    )
    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        "RecipeIngredient",
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.id",
    )


class RecipeStep(Base):
    __tablename__ = "recipe_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=1)
    instruction: Mapped[str] = mapped_column(Text())
    image_path: Mapped[Optional[str]] = mapped_column(String(512))

    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="steps")


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16), default="g", server_default="g")

    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="ingredients")
