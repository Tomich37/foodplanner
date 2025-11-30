from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.models.recipe import Recipe


@dataclass(frozen=True)
class RecipeCoverResolver:
    """Подбирает обложку для рецепта: пользовательскую или заглушку по тегу."""

    placeholders: Mapping[str, str]
    default_placeholder: str

    def resolve(self, recipe: Recipe) -> str:
        """Возвращает путь к обложке с учётом заглушек."""
        if recipe.image_path:
            return recipe.image_path
        tags = recipe.tags or []
        for tag in tags:
            if tag in self.placeholders:
                return self.placeholders[tag]
        return self.default_placeholder


recipe_cover_resolver = RecipeCoverResolver(
    placeholders={
        "breakfast": "/static/templates/zavtrak.jpg",
        "lunch": "/static/templates/obed.jpg",
        "dinner": "/static/templates/ujin.jpg",
    },
    default_placeholder="/static/templates/obed.jpg",
)
