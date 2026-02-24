from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class IngredientCanonical(Base):
    __tablename__ = "ingredient_catalog"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_ingredient_catalog_normalized_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    aliases: Mapped[list["IngredientAlias"]] = relationship(
        "IngredientAlias",
        back_populates="canonical",
        cascade="all, delete-orphan",
        order_by="IngredientAlias.alias.asc()",
    )


class IngredientAlias(Base):
    __tablename__ = "ingredient_aliases"
    __table_args__ = (
        UniqueConstraint("normalized_alias", name="uq_ingredient_aliases_normalized_alias"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_id: Mapped[int] = mapped_column(
        ForeignKey("ingredient_catalog.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    canonical: Mapped[IngredientCanonical] = relationship("IngredientCanonical", back_populates="aliases")
