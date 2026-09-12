from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from dealwatch.deals import (
    DealRules,
    DealSignalType,
    HistoryBaseline,
    evaluate_deal,
)
from dealwatch.models import Availability, PriceObservation, ProductIdentity, ProductOffer
from dealwatch.storage import ProductPriceHistory, StoredProduct

AS_OF = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def _product() -> ProductIdentity:
    return ProductIdentity(
        retailer="x-kom",
        retailer_product_id="1001",
        category="gpu",
        name="Acme GPU",
        brand="Acme",
        manufacturer_sku="ACME-1001",
        product_url="https://www.x-kom.pl/p/1001-acme-gpu.html",
        image_url=None,
    )


def _offer(
    price: str,
    *,
    availability: Availability = Availability.AVAILABLE,
    old_price: str | None = None,
) -> ProductOffer:
    return ProductOffer(
        product=_product(),
        price=Decimal(price),
        currency="PLN",
        availability=availability,
        previous_price=Decimal(old_price) if old_price else None,
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=AS_OF,
    )


def _observation(observed_at: datetime, price: str) -> PriceObservation:
    return PriceObservation(
        current_price=Decimal(price),
        currency="PLN",
        old_price=None,
        availability=Availability.AVAILABLE,
        observed_at=observed_at,
    )


def _hourly_history(days: int, *, price: str = "2000") -> list[PriceObservation]:
    start = AS_OF - timedelta(days=days)
    return [
        _observation(start + timedelta(hours=hour), price)
        for hour in range(days * 24)
    ]


def _history(observations: list[PriceObservation]) -> ProductPriceHistory:
    return ProductPriceHistory(
        product=StoredProduct(
            retailer="x-kom",
            retailer_product_id="1001",
            category="gpu",
            name="Acme GPU",
            product_url="https://www.x-kom.pl/p/1001-acme-gpu.html",
        ),
        observations=tuple(observations),
        recent_window_days=30,
        as_of=AS_OF,
    )


def _signal_types(evaluation) -> set[DealSignalType]:
    if evaluation.candidate is None:
        return set()
    return {signal.signal_type for signal in evaluation.candidate.signals}


def test_sufficient_thirty_day_median_qualifies_with_explained_baseline() -> None:
    evaluation = evaluate_deal(_offer("1750"), _history(_hourly_history(31)))

    assert evaluation.history_baseline is HistoryBaseline.SUFFICIENT_30D
    assert evaluation.candidate is not None
    assert DealSignalType.BELOW_30_DAY_MEDIAN in _signal_types(evaluation)
    assert evaluation.candidate.history_baseline is HistoryBaseline.SUFFICIENT_30D


def test_sufficient_seven_day_median_qualifies_without_thirty_day_history() -> None:
    evaluation = evaluate_deal(_offer("1800"), _history(_hourly_history(8)))

    assert evaluation.history_baseline is HistoryBaseline.SUFFICIENT_7D
    assert evaluation.candidate is not None
    assert DealSignalType.BELOW_7_DAY_MEDIAN in _signal_types(evaluation)
    assert DealSignalType.BELOW_30_DAY_MEDIAN not in _signal_types(evaluation)


def test_median_threshold_boundaries_are_inclusive() -> None:
    seven_day_rules = DealRules(
        thirty_day_median_percent=Decimal("99"),
        all_time_low_percent=Decimal("99"),
        thirty_day_low_percent=Decimal("99"),
    )
    thirty_day_rules = DealRules(
        seven_day_median_percent=Decimal("99"),
        all_time_low_percent=Decimal("99"),
        thirty_day_low_percent=Decimal("99"),
    )

    seven_day_exact = evaluate_deal(
        _offer("1840"),
        _history(_hourly_history(8)),
        rules=seven_day_rules,
    )
    seven_day_below = evaluate_deal(
        _offer("1841"),
        _history(_hourly_history(8)),
        rules=seven_day_rules,
    )
    thirty_day_exact = evaluate_deal(
        _offer("1800"),
        _history(_hourly_history(31)),
        rules=thirty_day_rules,
    )
    thirty_day_below = evaluate_deal(
        _offer("1801"),
        _history(_hourly_history(31)),
        rules=thirty_day_rules,
    )

    assert seven_day_exact.candidate is not None
    assert seven_day_below.candidate is None
    assert thirty_day_exact.candidate is not None
    assert thirty_day_below.candidate is None


def test_young_history_allows_a_meaningful_sharp_drop() -> None:
    history = _history([_observation(AS_OF - timedelta(hours=1), "2200")])
    evaluation = evaluate_deal(_offer("2000"), history)

    assert evaluation.history_baseline is HistoryBaseline.YOUNG_HISTORY
    assert evaluation.candidate is not None
    assert DealSignalType.PRICE_DROP in _signal_types(evaluation)


def test_strict_new_all_time_low_uses_five_percent_and_hundred_pln() -> None:
    history = _history([_observation(AS_OF - timedelta(hours=1), "2000")])
    evaluation = evaluate_deal(_offer("1900"), history)

    assert evaluation.candidate is not None
    assert DealSignalType.NEW_ALL_TIME_LOW in _signal_types(evaluation)
    price_drop = next(
        signal for signal in evaluation.signals if signal.signal_type is DealSignalType.PRICE_DROP
    )
    assert not price_drop.qualifies


def test_new_thirty_day_low_requires_eight_percent_and_sufficient_coverage() -> None:
    rules = DealRules(
        seven_day_median_percent=Decimal("99"),
        thirty_day_median_percent=Decimal("99"),
        all_time_low_percent=Decimal("99"),
    )
    history = _history(_hourly_history(31))

    qualified = evaluate_deal(_offer("1840"), history, rules=rules)
    below_threshold = evaluate_deal(_offer("1841"), history, rules=rules)

    assert qualified.candidate is not None
    assert DealSignalType.NEW_30_DAY_LOW in _signal_types(qualified)
    assert below_threshold.candidate is None


def test_equal_low_and_tiny_fluctuation_do_not_qualify() -> None:
    history = _history([_observation(AS_OF - timedelta(hours=1), "2000")])

    equal_low = evaluate_deal(_offer("2000"), history)
    tiny_drop = evaluate_deal(_offer("1950"), history)

    assert equal_low.candidate is None
    assert tiny_drop.candidate is None


def test_sufficient_history_does_not_use_the_sharp_drop_as_the_only_signal() -> None:
    observations = _hourly_history(8, price="1900")
    observations[-1] = _observation(AS_OF - timedelta(hours=1), "2200")

    evaluation = evaluate_deal(_offer("2000"), _history(observations))

    assert evaluation.history_baseline is HistoryBaseline.SUFFICIENT_7D
    assert evaluation.candidate is None
    assert any(
        signal.signal_type is DealSignalType.PRICE_DROP and signal.qualifies
        for signal in evaluation.signals
    )


def test_unavailable_offer_and_price_increase_do_not_qualify() -> None:
    history = _history([_observation(AS_OF - timedelta(hours=1), "2000")])

    unavailable = evaluate_deal(
        _offer("1800", availability=Availability.OUT_OF_STOCK),
        history,
    )
    increase = evaluate_deal(_offer("2100"), history)

    assert unavailable.candidate is None
    assert unavailable.non_qualification_reasons == ("product_is_not_available",)
    assert increase.candidate is None


def test_gapped_history_is_reported_as_young_history() -> None:
    history = _history(
        [
            _observation(AS_OF - timedelta(days=8), "2000"),
            _observation(AS_OF - timedelta(days=4), "2000"),
        ]
    )
    evaluation = evaluate_deal(_offer("1950"), history)

    assert evaluation.history_baseline is HistoryBaseline.YOUNG_HISTORY
    assert evaluation.candidate is None


def test_current_offer_is_excluded_from_its_median_baseline() -> None:
    evaluation = evaluate_deal(_offer("1800"), _history(_hourly_history(8)))
    median_signal = next(
        signal
        for signal in evaluation.signals
        if signal.signal_type is DealSignalType.BELOW_7_DAY_MEDIAN
    )

    assert median_signal.reference_price == Decimal("2000.00")


def test_retailer_old_price_support_does_not_qualify_by_itself() -> None:
    evaluation = evaluate_deal(_offer("2000", old_price="2500"), _history([]))

    assert evaluation.candidate is None
    assert evaluation.non_qualification_reasons == (
        "retailer_old_price_is_supporting_evidence_only",
    )


def test_fingerprints_are_stable_for_same_price_and_change_for_new_price() -> None:
    history = _history([_observation(AS_OF - timedelta(hours=1), "2200")])

    first = evaluate_deal(_offer("2000"), history)
    repeated = evaluate_deal(_offer("2000"), history)
    lower_price = evaluate_deal(_offer("1900"), history)

    assert first.candidate is not None
    assert repeated.candidate is not None
    assert lower_price.candidate is not None
    assert first.candidate.fingerprint == repeated.candidate.fingerprint
    assert first.candidate.fingerprint != lower_price.candidate.fingerprint
