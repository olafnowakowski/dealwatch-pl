from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from dealwatch.history import analyze_price_history
from dealwatch.models import Availability, PriceObservation

AS_OF = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _observation(
    *,
    observed_at: datetime,
    price: str,
    availability: Availability = Availability.AVAILABLE,
) -> PriceObservation:
    return PriceObservation(
        current_price=Decimal(price),
        currency="PLN",
        old_price=None,
        availability=availability,
        observed_at=observed_at,
    )


def _hourly_observations(days: int, *, price: str = "100") -> list[PriceObservation]:
    start = AS_OF - timedelta(days=days)
    return [
        _observation(observed_at=start + timedelta(hours=hour), price=price)
        for hour in range(days * 24 + 1)
    ]


def _window(analysis, days: int):
    return next(window for window in analysis.windows if window.window_days == days)


def test_one_observation_reports_insufficient_history() -> None:
    analysis = analyze_price_history(
        [_observation(observed_at=AS_OF, price="100")],
        as_of=AS_OF,
    )

    assert not analysis.price_change.is_sufficient
    assert analysis.price_change.absolute_change is None
    for days in (7, 30):
        statistics = _window(analysis, days)
        assert not statistics.is_sufficient
        assert statistics.available_observation_count == 1
        assert statistics.coverage_seconds == 0
        assert statistics.to_dict()["status"] == "insufficient_history"
        assert statistics.to_dict()["average"] is None
        assert statistics.to_dict()["median"] is None


def test_unchanged_hourly_price_has_zero_change_and_sufficient_seven_day_statistics() -> None:
    analysis = analyze_price_history(_hourly_observations(8), as_of=AS_OF)
    statistics = _window(analysis, 7)

    assert analysis.price_change.is_sufficient
    assert analysis.price_change.absolute_change == Decimal("0.00")
    assert analysis.price_change.percentage_change == Decimal("0.00")
    assert statistics.is_sufficient
    assert statistics.available_observation_count == 169
    assert statistics.required_observation_count == 136
    assert statistics.coverage_seconds == 7 * 24 * 60 * 60
    assert statistics.average == Decimal("100.00")
    assert statistics.median == Decimal("100.00")


def test_price_decrease_is_measured_against_the_previous_available_observation() -> None:
    analysis = analyze_price_history(
        [
            _observation(observed_at=AS_OF - timedelta(hours=2), price="200"),
            _observation(
                observed_at=AS_OF - timedelta(hours=1),
                price="1",
                availability=Availability.OUT_OF_STOCK,
            ),
            _observation(observed_at=AS_OF, price="150"),
        ],
        as_of=AS_OF,
    )

    assert analysis.price_change.absolute_change == Decimal("-50.00")
    assert analysis.price_change.percentage_change == Decimal("-25.00")


def test_price_increase_is_measured_against_the_previous_available_observation() -> None:
    analysis = analyze_price_history(
        [
            _observation(observed_at=AS_OF - timedelta(hours=1), price="100"),
            _observation(observed_at=AS_OF, price="150"),
        ],
        as_of=AS_OF,
    )

    assert analysis.price_change.absolute_change == Decimal("50.00")
    assert analysis.price_change.percentage_change == Decimal("50.00")


def test_collection_gap_does_not_count_as_observed_price_coverage() -> None:
    observations = [
        _observation(observed_at=AS_OF - timedelta(days=7), price="100"),
        _observation(observed_at=AS_OF - timedelta(days=4), price="100"),
        _observation(observed_at=AS_OF, price="100"),
    ]
    statistics = _window(analyze_price_history(observations, as_of=AS_OF), 7)

    assert statistics.available_observation_count == 3
    assert statistics.coverage_seconds == 0
    assert not statistics.is_sufficient
    assert statistics.to_dict()["average"] is None
    assert statistics.to_dict()["median"] is None


def test_seven_day_window_requires_coverage_and_hourly_observation_count() -> None:
    sufficient = _window(analyze_price_history(_hourly_observations(8), as_of=AS_OF), 7)
    insufficient = _window(analyze_price_history(_hourly_observations(5), as_of=AS_OF), 7)

    assert sufficient.is_sufficient
    assert sufficient.required_observation_count == 136
    assert sufficient.available_observation_count >= sufficient.required_observation_count
    assert sufficient.coverage_seconds >= sufficient.required_coverage_seconds
    assert not insufficient.is_sufficient
    assert insufficient.coverage_seconds < insufficient.required_coverage_seconds
    assert insufficient.to_dict()["status"] == "insufficient_history"


def test_thirty_day_window_requires_coverage_and_hourly_observation_count() -> None:
    sufficient = _window(analyze_price_history(_hourly_observations(31), as_of=AS_OF), 30)
    insufficient = _window(analyze_price_history(_hourly_observations(20), as_of=AS_OF), 30)

    assert sufficient.is_sufficient
    assert sufficient.available_observation_count == 721
    assert sufficient.required_observation_count == 577
    assert sufficient.coverage_seconds == 30 * 24 * 60 * 60
    assert sufficient.average == Decimal("100.00")
    assert sufficient.median == Decimal("100.00")
    assert not insufficient.is_sufficient
    assert insufficient.coverage_seconds < insufficient.required_coverage_seconds
    assert insufficient.to_dict()["status"] == "insufficient_history"
