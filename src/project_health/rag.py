"""Red / Amber / Green status with configurable thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RAG(StrEnum):
    GREEN = "Green"
    AMBER = "Amber"
    RED = "Red"

    @property
    def severity(self) -> int:
        return {RAG.GREEN: 0, RAG.AMBER: 1, RAG.RED: 2}[self]


@dataclass(frozen=True)
class RAGThresholds:
    """An index at or above ``*_green`` is Green, at or above ``*_amber`` is Amber,
    otherwise Red. ``overdue_red`` escalates a project to Red when it has at least
    that many overdue tasks (0 disables the rule)."""

    cpi_green: float = 0.95
    cpi_amber: float = 0.85
    spi_green: float = 0.95
    spi_amber: float = 0.85
    overdue_amber: int = 1
    overdue_red: int = 3

    def __post_init__(self) -> None:
        for name in ("cpi", "spi"):
            green = getattr(self, f"{name}_green")
            amber = getattr(self, f"{name}_amber")
            if green <= 0 or amber <= 0:
                raise ValueError(f"{name.upper()} thresholds must be positive")
            if amber > green:
                raise ValueError(f"{name.upper()} amber threshold cannot exceed green threshold")
        if self.overdue_amber < 0 or self.overdue_red < 0:
            raise ValueError("Overdue thresholds cannot be negative")
        if self.overdue_amber and self.overdue_red and self.overdue_amber > self.overdue_red:
            raise ValueError("Overdue amber count cannot exceed overdue red count")


def index_status(value: float | None, green: float, amber: float) -> RAG:
    """Classify a performance index. ``None`` (no data yet) counts as on track."""
    if value is None:
        return RAG.GREEN
    if value >= green:
        return RAG.GREEN
    if value >= amber:
        return RAG.AMBER
    return RAG.RED


def worst(*statuses: RAG) -> RAG:
    return max(statuses, key=lambda s: s.severity, default=RAG.GREEN)


def overall_status(
    cpi: float | None,
    spi: float | None,
    overdue_count: int = 0,
    thresholds: RAGThresholds | None = None,
) -> RAG:
    """Overall project status: the worst of cost, schedule, and overdue signals."""
    th = thresholds or RAGThresholds()
    overdue = RAG.GREEN
    if th.overdue_red and overdue_count >= th.overdue_red:
        overdue = RAG.RED
    elif th.overdue_amber and overdue_count >= th.overdue_amber:
        overdue = RAG.AMBER
    return worst(
        index_status(cpi, th.cpi_green, th.cpi_amber),
        index_status(spi, th.spi_green, th.spi_amber),
        overdue,
    )


def explain_status(
    cpi: float | None,
    spi: float | None,
    overdue_count: int = 0,
    thresholds: RAGThresholds | None = None,
) -> list[str]:
    """Plain English drivers behind a non-green status, for the executive summary."""
    th = thresholds or RAGThresholds()
    reasons: list[str] = []
    if index_status(cpi, th.cpi_green, th.cpi_amber) is not RAG.GREEN:
        reasons.append(f"over budget (CPI {cpi:.2f} vs target {th.cpi_green:.2f})")
    if index_status(spi, th.spi_green, th.spi_amber) is not RAG.GREEN:
        reasons.append(f"behind schedule (SPI {spi:.2f} vs target {th.spi_green:.2f})")
    if th.overdue_amber and overdue_count >= th.overdue_amber:
        plural = "s" if overdue_count != 1 else ""
        reasons.append(f"{overdue_count} overdue task{plural}")
    return reasons
