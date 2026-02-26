from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression

from app.db.base import Base


class IngredientCanonical(Base):
    __tablename__ = "ingredient_catalog"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_ingredient_catalog_normalized_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    current_price_rub: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_price_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    current_price_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="RUB", default="RUB")
    current_price_region: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="RU_AVG", default="RU_AVG"
    )
    current_price_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_price_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    price_is_stale: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=expression.true(),
        default=True,
    )
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
