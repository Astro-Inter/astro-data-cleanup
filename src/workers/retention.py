"""Cálculos compartilhados de retenção temporal."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timezone


def calendar_years_before(moment: datetime, years: int) -> datetime:
    """Retorna o instante equivalente em UTC, recuado por anos-calendário."""
    if moment.tzinfo is None:
        raise ValueError("O relógio do worker deve fornecer uma data com fuso horário.")
    if years < 1:
        raise ValueError("A quantidade de anos deve ser maior que zero.")

    normalized = moment.astimezone(timezone.utc)
    target_year = normalized.year - years
    target_day = min(normalized.day, monthrange(target_year, normalized.month)[1])
    return normalized.replace(year=target_year, day=target_day)
