"""The configurable, explainable productivity score."""

from app.domain.productivity.scoring import (
    DayMetrics,
    ProductivityScore,
    ScoreComponent,
    score_day,
)
from app.domain.productivity.weights import (
    COMPONENT_LABELS,
    SETTINGS_KEY,
    ProductivityWeights,
)

__all__ = [
    "COMPONENT_LABELS",
    "SETTINGS_KEY",
    "DayMetrics",
    "ProductivityScore",
    "ProductivityWeights",
    "ScoreComponent",
    "score_day",
]
