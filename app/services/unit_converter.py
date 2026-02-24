from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

UnitType = Literal["mass", "volume", "other", "count"]


@dataclass(frozen=True)
class UnitInfo:
    key: str
    label: str
    unit_type: UnitType
    factor_to_base: float = 1.0  # g или мл для базовых типов


class UnitConverter:
    """Утилита для работы с единицами измерения ингредиентов и человекочитаемым выводом."""

    def __init__(self) -> None:
        self.units: dict[str, UnitInfo] = {
            "g": UnitInfo(key="g", label="г", unit_type="mass", factor_to_base=1),
            "ml": UnitInfo(key="ml", label="мл", unit_type="volume", factor_to_base=1),
            "tbsp": UnitInfo(key="tbsp", label="ст. л.", unit_type="volume", factor_to_base=15),
            "tsp": UnitInfo(key="tsp", label="ч. л.", unit_type="volume", factor_to_base=5),
            "pcs": UnitInfo(key="pcs", label="штука", unit_type="count", factor_to_base=1),
            "taste": UnitInfo(key="taste", label="по вкусу", unit_type="other", factor_to_base=0),
        }
        self.default_unit = "g"

    def normalize_unit(self, value: Optional[str]) -> str:
        """Возвращает поддерживаемый ключ единицы измерения, либо базовый."""
        if not value:
            return self.default_unit
        value = value.strip().lower()
        return value if value in self.units else self.default_unit

    def to_base(self, amount: float, unit: str) -> tuple[Optional[float], UnitType]:
        """Переводит количество в базовые единицы (г/мл) и возвращает тип измерения."""
        info = self.units.get(self.normalize_unit(unit), self.units[self.default_unit])
        if info.unit_type == "other" or amount is None:
            return None, info.unit_type
        return float(amount) * info.factor_to_base, info.unit_type

    @staticmethod
    def _format_value(value: float) -> str:
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text or "0"

    @staticmethod
    def _pluralize_count(value: float) -> str:
        if value != int(value):
            return "штуки"
        number = int(value)
        last_two = number % 100
        last_one = number % 10
        if 11 <= last_two <= 14:
            return "штук"
        if last_one == 1:
            return "штука"
        if 2 <= last_one <= 4:
            return "штуки"
        return "штук"

    def format_total(self, base_amount: float, unit_type: UnitType) -> tuple[float, str]:
        """Возвращает значение и подпись в удобных единицах (кг/л, г/мл)."""
        if unit_type == "mass":
            if base_amount >= 1000:
                return base_amount / 1000, "кг"
            return base_amount, "г"
        if unit_type == "volume":
            if base_amount >= 1000:
                return base_amount / 1000, "л"
            return base_amount, "мл"
        if unit_type == "count":
            return base_amount, "шт."
        return base_amount, ""

    def format_human(self, amount: float, unit: Optional[str], keep_input_unit: bool = False) -> str:
        """Форматирует количество для отображения (используется в рецептах и списках)."""
        info = self.units.get(self.normalize_unit(unit), self.units[self.default_unit])
        if info.unit_type == "other":
            return info.label
        if amount is None or amount <= 0:
            return "—"
        if info.unit_type == "count":
            value = float(amount)
            label = self._pluralize_count(value)
            return f"{self._format_value(value)} {label}"
        if keep_input_unit:
            return f"{self._format_value(float(amount))} {info.label}".strip()
        base_amount, unit_type = self.to_base(amount, info.key)
        if base_amount is None:
            return info.label
        value, label = self.format_total(base_amount, unit_type)
        value_str = self._format_value(value)
        return f"{value_str} {label}".strip()
