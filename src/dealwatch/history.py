"""Reusable price-history calculations for future deal evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from dealwatch.models import Availability, PriceObservation

EXPECTED_COLLECTION_INTERVAL = timedelta(hours=1)
MAX_CONTIGUOUS_GAP = timedelta(hours=2)
MINIMUM_COVERAGE_RATIO = Decimal("0.80")
STATISTIC_WINDOWS_DAYS = (7, 30)


@dataclass(frozen=True, slots=True)
class PriceChange:
    """Change from the latest available observation to the prior available one."""

    current: PriceObservation | None
    previous: PriceObservation | None
    absolute_change: Decimal | None
    percentage_change: Decimal | None

    @property
    def is_sufficient(self) -> bool:
        return self.absolute_change is not None and self.percentage_change is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "sufficient" if self.is_sufficient else "insufficient_history",
            "current_observation": self.current.to_dict() if self.current else None,
            "previous_available_observation": self.previous.to_dict() if self.previous else None,
            "absolute_change": _decimal_text(self.absolute_change),
            "percentage_change": _decimal_text(self.percentage_change),
        }


@dataclass(frozen=True, slots=True)
class WindowStatistics:
    """Coverage-aware, time-weighted statistics for one requested time window."""

    window_days: int
    available_observation_count: int
    required_observation_count: int
    coverage_seconds: int
    required_coverage_seconds: int
    average: Decimal | None
    median: Decimal | None

    @property
    def is_sufficient(self) -> bool:
        return (
            self.available_observation_count >= self.required_observation_count
            and self.coverage_seconds >= self.required_coverage_seconds
        )

    def to_dict(self) -> dict[str, object]:
        window_seconds = int(timedelta(days=self.window_days).total_seconds())
        coverage_ratio = Decimal(self.coverage_seconds) / Decimal(window_seconds)
        return {
            "status": "sufficient" if self.is_sufficient else "insufficient_history",
            "window_days": self.window_days,
            "available_observation_count": self.available_observation_count,
            "required_observation_count": self.required_observation_count,
            "coverage_seconds": self.coverage_seconds,
            "coverage_ratio": _decimal_text(_quantize(coverage_ratio, Decimal("0.0001"))),
            "required_coverage_seconds": self.required_coverage_seconds,
            "average": _decimal_text(self.average) if self.is_sufficient else None,
            "median": _decimal_text(self.median) if self.is_sufficient else None,
        }


@dataclass(frozen=True, slots=True)
class PriceHistoryAnalysis:
    """All M5 metrics derived from a product's available-price observations."""

    price_change: PriceChange
    windows: tuple[WindowStatistics, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "price_change": self.price_change.to_dict(),
            "windows": {f"{window.window_days}_day": window.to_dict() for window in self.windows},
        }


def analyze_price_history(
    observations: Iterable[PriceObservation],
    *,
    as_of: datetime,
) -> PriceHistoryAnalysis:
    """Calculate M5 metrics while making incomplete collection coverage explicit."""

    ordered = tuple(
        sorted(
            (item for item in observations if item.observed_at <= as_of),
            key=lambda item: item.observed_at,
        )
    )
    return PriceHistoryAnalysis(
        price_change=_price_change(ordered),
        windows=tuple(
            _window_statistics(ordered, as_of=as_of, window_days=days)
            for days in STATISTIC_WINDOWS_DAYS
        ),
    )


def _price_change(observations: tuple[PriceObservation, ...]) -> PriceChange:
    available = [item for item in observations if item.availability is Availability.AVAILABLE]
    current = available[-1] if available else None
    previous = available[-2] if len(available) > 1 else None
    if current is None or previous is None or previous.current_price == 0:
        return PriceChange(
            current=current,
            previous=previous,
            absolute_change=None,
            percentage_change=None,
        )
    absolute_change = _quantize(current.current_price - previous.current_price, Decimal("0.01"))
    percentage_change = _quantize(
        (absolute_change / previous.current_price) * Decimal("100"), Decimal("0.01")
    )
    return PriceChange(
        current=current,
        previous=previous,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
    )


def _window_statistics(
    observations: tuple[PriceObservation, ...], *, as_of: datetime, window_days: int
) -> WindowStatistics:
    window_start = as_of - timedelta(days=window_days)
    window_seconds = int(timedelta(days=window_days).total_seconds())
    required_observations = _required_observation_count(window_days)
    required_coverage = int(Decimal(window_seconds) * MINIMUM_COVERAGE_RATIO)
    in_window_available_count = sum(
        item.availability is Availability.AVAILABLE and window_start <= item.observed_at <= as_of
        for item in observations
    )
    weighted_segments = _available_segments(observations, window_start=window_start, as_of=as_of)
    coverage_seconds = sum(duration for _, duration in weighted_segments)
    if coverage_seconds == 0:
        return WindowStatistics(
            window_days=window_days,
            available_observation_count=in_window_available_count,
            required_observation_count=required_observations,
            coverage_seconds=0,
            required_coverage_seconds=required_coverage,
            average=None,
            median=None,
        )
    weighted_sum = sum((price * duration for price, duration in weighted_segments), Decimal("0"))
    average = _quantize(weighted_sum / Decimal(coverage_seconds), Decimal("0.01"))
    median = _weighted_median(weighted_segments, coverage_seconds)
    return WindowStatistics(
        window_days=window_days,
        available_observation_count=in_window_available_count,
        required_observation_count=required_observations,
        coverage_seconds=coverage_seconds,
        required_coverage_seconds=required_coverage,
        average=average,
        median=median,
    )


def _available_segments(
    observations: tuple[PriceObservation, ...],
    *,
    window_start: datetime,
    as_of: datetime,
) -> list[tuple[Decimal, int]]:
    segments: list[tuple[Decimal, int]] = []
    for index, observation in enumerate(observations):
        if observation.availability is not Availability.AVAILABLE:
            continue
        next_observed_at = (
            observations[index + 1].observed_at if index + 1 < len(observations) else as_of
        )
        if next_observed_at - observation.observed_at > MAX_CONTIGUOUS_GAP:
            continue
        segment_start = max(observation.observed_at, window_start)
        segment_end = min(next_observed_at, as_of)
        if segment_end > segment_start:
            duration_seconds = int((segment_end - segment_start).total_seconds())
            segments.append((observation.current_price, duration_seconds))
    return segments


def _weighted_median(segments: list[tuple[Decimal, int]], coverage_seconds: int) -> Decimal:
    cumulative_seconds = 0
    midpoint = Decimal(coverage_seconds) / Decimal("2")
    for price, duration in sorted(segments, key=lambda segment: segment[0]):
        cumulative_seconds += duration
        if Decimal(cumulative_seconds) >= midpoint:
            return _quantize(price, Decimal("0.01"))
    raise RuntimeError("Weighted median requires at least one covered segment")


def _required_observation_count(window_days: int) -> int:
    window_seconds = int(timedelta(days=window_days).total_seconds())
    interval_seconds = int(EXPECTED_COLLECTION_INTERVAL.total_seconds())
    expected_observations = (window_seconds // interval_seconds) + 1
    required = Decimal(expected_observations) * MINIMUM_COVERAGE_RATIO
    return int(required.to_integral_value(rounding=ROUND_CEILING))


def _quantize(value: Decimal, precision: Decimal) -> Decimal:
    return value.quantize(precision, rounding=ROUND_HALF_UP)


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None
