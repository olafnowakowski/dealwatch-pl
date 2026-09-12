"""Deterministic, transport-independent deal candidate evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from dealwatch.history import PriceHistoryAnalysis, WindowStatistics, analyze_price_history
from dealwatch.models import (
    Availability,
    PriceObservation,
    ProductIdentity,
    ProductOffer,
    ReferencePriceEvidence,
    ReferencePriceKind,
    ReferencePriceScope,
)
from dealwatch.storage import ProductPriceHistory


class HistoryBaseline(StrEnum):
    """The strongest sufficient local-history window available to an evaluation."""

    YOUNG_HISTORY = "young_history"
    SUFFICIENT_7D = "sufficient_7d"
    SUFFICIENT_30D = "sufficient_30d"


class DealSignalType(StrEnum):
    """Evidence inspected by the first rule-based deal engine."""

    PRICE_DROP = "price_drop_from_previous"
    BELOW_7_DAY_MEDIAN = "below_7_day_median"
    BELOW_30_DAY_MEDIAN = "below_30_day_median"
    NEW_ALL_TIME_LOW = "new_all_time_low"
    NEW_30_DAY_LOW = "new_30_day_low"
    RETAILER_OLD_PRICE = "retailer_old_price_support"
    XCOM_REPORTED_30_DAY_MINIMUM = "below_xkom_reported_30d_minimum"


@dataclass(frozen=True, slots=True)
class DealRules:
    """Tunable first-version thresholds for a PLN GPU deal candidate."""

    minimum_absolute_savings: Decimal = Decimal("100")
    sharp_drop_percent: Decimal = Decimal("8")
    seven_day_median_percent: Decimal = Decimal("8")
    thirty_day_median_percent: Decimal = Decimal("10")
    all_time_low_percent: Decimal = Decimal("5")
    thirty_day_low_percent: Decimal = Decimal("8")
    retailer_old_price_percent: Decimal = Decimal("10")
    xkom_reference_bootstrap_percent: Decimal = Decimal("8")
    enable_xkom_reference_bootstrap: bool = False


DEFAULT_DEAL_RULES = DealRules()


@dataclass(frozen=True, slots=True)
class DealSignal:
    """One inspected price comparison and whether it meets its threshold."""

    signal_type: DealSignalType
    reference_price: Decimal
    absolute_savings: Decimal
    percentage_savings: Decimal
    qualifies: bool
    supports_candidate: bool = False
    reference_source: str | None = None
    reference_scope: ReferencePriceScope | None = None
    reference_kind: ReferencePriceKind | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.signal_type.value,
            "reference_price": _decimal_text(self.reference_price),
            "absolute_savings": _decimal_text(self.absolute_savings),
            "percentage_savings": _decimal_text(self.percentage_savings),
            "qualifies": self.qualifies,
            "supports_candidate": self.supports_candidate,
            "reference_source": self.reference_source,
            "reference_scope": self.reference_scope.value if self.reference_scope else None,
            "reference_kind": self.reference_kind.value if self.reference_kind else None,
        }


@dataclass(frozen=True, slots=True)
class DealCandidate:
    """An explained, caller-owned candidate for a future delivery decision."""

    product: ProductIdentity
    price: Decimal
    currency: str
    observed_at: datetime
    history_baseline: HistoryBaseline
    signals: tuple[DealSignal, ...]
    fingerprint: str
    alert_type: str = "deal_candidate"

    @property
    def explanation(self) -> str:
        labels = ", ".join(signal.signal_type.value for signal in self.signals)
        return f"Qualified by {labels}."

    def to_dict(self) -> dict[str, object]:
        return {
            "product": asdict(self.product),
            "price": _decimal_text(self.price),
            "currency": self.currency,
            "observed_at": self.observed_at.isoformat(),
            "history_baseline": self.history_baseline.value,
            "alert_type": self.alert_type,
            "fingerprint": self.fingerprint,
            "explanation": self.explanation,
            "signals": [signal.to_dict() for signal in self.signals],
        }


@dataclass(frozen=True, slots=True)
class DealEvaluation:
    """The full transparent result for one newly observed product offer."""

    history_baseline: HistoryBaseline
    history_analysis: PriceHistoryAnalysis
    signals: tuple[DealSignal, ...]
    reference_evidence: tuple[ReferencePriceEvidence, ...]
    non_qualification_reasons: tuple[str, ...]
    candidate: DealCandidate | None

    def to_dict(self) -> dict[str, object]:
        return {
            "history_baseline": self.history_baseline.value,
            "history": self.history_analysis.to_dict(),
            "signals": [signal.to_dict() for signal in self.signals],
            "reference_evidence": [evidence.to_dict() for evidence in self.reference_evidence],
            "non_qualification_reasons": list(self.non_qualification_reasons),
            "candidate": self.candidate.to_dict() if self.candidate else None,
        }


def evaluate_deal(
    offer: ProductOffer,
    history: ProductPriceHistory,
    *,
    rules: DealRules = DEFAULT_DEAL_RULES,
) -> DealEvaluation:
    """Evaluate one offer using only history that predates the current observation."""

    prior_observations = tuple(
        observation
        for observation in history.observations
        if observation.observed_at < offer.observed_at
    )
    analysis = analyze_price_history(prior_observations, as_of=offer.observed_at)
    seven_day = _window(analysis, 7)
    thirty_day = _window(analysis, 30)
    baseline = _history_baseline(seven_day, thirty_day)
    if offer.availability is not Availability.AVAILABLE:
        return DealEvaluation(
            history_baseline=baseline,
            history_analysis=analysis,
            signals=(),
            reference_evidence=offer.reference_price_evidence,
            non_qualification_reasons=("product_is_not_available",),
            candidate=None,
        )

    signals = _inspect_signals(
        offer,
        prior_observations,
        seven_day=seven_day,
        thirty_day=thirty_day,
        rules=rules,
    )
    qualifying = _qualifying_signals(signals, baseline, rules)
    if qualifying:
        supporting = tuple(
            replace(signal, supports_candidate=True)
            for signal in signals
            if signal not in qualifying
            and signal.qualifies
            and signal.signal_type
            in {
                DealSignalType.RETAILER_OLD_PRICE,
                DealSignalType.XCOM_REPORTED_30_DAY_MINIMUM,
            }
        )
        candidate = DealCandidate(
            product=offer.product,
            price=offer.price,
            currency=offer.currency,
            observed_at=offer.observed_at,
            history_baseline=baseline,
            signals=qualifying + supporting,
            fingerprint=_candidate_fingerprint(offer),
        )
        return DealEvaluation(
            history_baseline=baseline,
            history_analysis=analysis,
            signals=signals,
            reference_evidence=offer.reference_price_evidence,
            non_qualification_reasons=(),
            candidate=candidate,
        )

    return DealEvaluation(
        history_baseline=baseline,
        history_analysis=analysis,
        signals=signals,
        reference_evidence=offer.reference_price_evidence,
        non_qualification_reasons=_non_qualification_reasons(signals, baseline, rules),
        candidate=None,
    )


def _inspect_signals(
    offer: ProductOffer,
    prior_observations: tuple[PriceObservation, ...],
    *,
    seven_day: WindowStatistics,
    thirty_day: WindowStatistics,
    rules: DealRules,
) -> tuple[DealSignal, ...]:
    signals: list[DealSignal] = []
    previous = _latest_available(prior_observations)
    if previous:
        signals.append(
            _compare(
                DealSignalType.PRICE_DROP,
                offer.price,
                previous.current_price,
                rules.sharp_drop_percent,
                rules,
            )
        )
    if seven_day.is_sufficient and seven_day.median is not None:
        signals.append(
            _compare(
                DealSignalType.BELOW_7_DAY_MEDIAN,
                offer.price,
                seven_day.median,
                rules.seven_day_median_percent,
                rules,
            )
        )
    if thirty_day.is_sufficient and thirty_day.median is not None:
        signals.append(
            _compare(
                DealSignalType.BELOW_30_DAY_MEDIAN,
                offer.price,
                thirty_day.median,
                rules.thirty_day_median_percent,
                rules,
            )
        )
        recent_low = _lowest_available(
            observation
            for observation in prior_observations
            if observation.observed_at >= offer.observed_at - timedelta(days=30)
        )
        if recent_low:
            signals.append(
                _compare(
                    DealSignalType.NEW_30_DAY_LOW,
                    offer.price,
                    recent_low.current_price,
                    rules.thirty_day_low_percent,
                    rules,
                )
            )
    all_time_low = _lowest_available(prior_observations)
    if all_time_low:
        signals.append(
            _compare(
                DealSignalType.NEW_ALL_TIME_LOW,
                offer.price,
                all_time_low.current_price,
                rules.all_time_low_percent,
                rules,
            )
        )
    if offer.previous_price is not None:
        signals.append(
            _compare(
                DealSignalType.RETAILER_OLD_PRICE,
                offer.price,
                offer.previous_price,
                rules.retailer_old_price_percent,
                rules,
            )
        )
    if reference := usable_xkom_reference_evidence(offer):
        signals.append(
            _compare(
                DealSignalType.XCOM_REPORTED_30_DAY_MINIMUM,
                offer.price,
                reference.price,
                rules.xkom_reference_bootstrap_percent,
                rules,
                reference_evidence=reference,
            )
        )
    return tuple(signals)


def _qualifying_signals(
    signals: tuple[DealSignal, ...], baseline: HistoryBaseline, rules: DealRules
) -> tuple[DealSignal, ...]:
    historical_types = {
        DealSignalType.BELOW_7_DAY_MEDIAN,
        DealSignalType.BELOW_30_DAY_MEDIAN,
        DealSignalType.NEW_ALL_TIME_LOW,
        DealSignalType.NEW_30_DAY_LOW,
    }
    if baseline is HistoryBaseline.YOUNG_HISTORY:
        eligible_types = historical_types | {DealSignalType.PRICE_DROP}
        if rules.enable_xkom_reference_bootstrap:
            eligible_types.add(DealSignalType.XCOM_REPORTED_30_DAY_MINIMUM)
    else:
        eligible_types = historical_types
    return tuple(
        signal
        for signal in signals
        if signal.signal_type in eligible_types and signal.qualifies
    )


def _non_qualification_reasons(
    signals: tuple[DealSignal, ...], baseline: HistoryBaseline, rules: DealRules
) -> tuple[str, ...]:
    retailer_support = any(
        signal.signal_type is DealSignalType.RETAILER_OLD_PRICE and signal.qualifies
        for signal in signals
    )
    if retailer_support:
        return ("retailer_old_price_is_supporting_evidence_only",)
    reference_bootstrap = any(
        signal.signal_type is DealSignalType.XCOM_REPORTED_30_DAY_MINIMUM and signal.qualifies
        for signal in signals
    )
    if reference_bootstrap and not rules.enable_xkom_reference_bootstrap:
        return ("xkom_reference_bootstrap_is_disabled",)
    if baseline is HistoryBaseline.YOUNG_HISTORY:
        return ("young_history_without_a_meaningful_price_drop",)
    return ("sufficient_history_without_a_meaningful_historical_discount",)


def _history_baseline(
    seven_day: WindowStatistics, thirty_day: WindowStatistics
) -> HistoryBaseline:
    if thirty_day.is_sufficient:
        return HistoryBaseline.SUFFICIENT_30D
    if seven_day.is_sufficient:
        return HistoryBaseline.SUFFICIENT_7D
    return HistoryBaseline.YOUNG_HISTORY


def _latest_available(observations: tuple[PriceObservation, ...]) -> PriceObservation | None:
    return next(
        (
            observation
            for observation in reversed(observations)
            if observation.availability is Availability.AVAILABLE
        ),
        None,
    )


def _lowest_available(observations: Iterable[PriceObservation]) -> PriceObservation | None:
    available = [
        observation
        for observation in observations
        if observation.availability is Availability.AVAILABLE
    ]
    return min(
        available,
        key=lambda observation: (observation.current_price, observation.observed_at),
        default=None,
    )


def _compare(
    signal_type: DealSignalType,
    current_price: Decimal,
    reference_price: Decimal,
    required_percent: Decimal,
    rules: DealRules,
    *,
    reference_evidence: ReferencePriceEvidence | None = None,
) -> DealSignal:
    raw_absolute_savings = reference_price - current_price
    raw_percentage_savings = (
        (raw_absolute_savings / reference_price) * Decimal("100")
        if reference_price > 0
        else Decimal("0")
    )
    qualifies = (
        raw_absolute_savings >= rules.minimum_absolute_savings
        and raw_percentage_savings >= required_percent
    )
    return DealSignal(
        signal_type=signal_type,
        reference_price=reference_price,
        absolute_savings=_quantize(raw_absolute_savings),
        percentage_savings=_quantize(raw_percentage_savings),
        qualifies=qualifies,
        reference_source=reference_evidence.source if reference_evidence else None,
        reference_scope=reference_evidence.scope if reference_evidence else None,
        reference_kind=reference_evidence.kind if reference_evidence else None,
    )


def usable_xkom_reference_evidence(offer: ProductOffer) -> ReferencePriceEvidence | None:
    """Return the current direct x-kom 30-day reference when it is usable."""

    return next(
        (
            evidence
            for evidence in offer.reference_price_evidence
            if evidence.source == "x-kom"
            and evidence.source == offer.product.retailer
            and evidence.scope is ReferencePriceScope.RETAILER
            and evidence.kind is ReferencePriceKind.XCOM_REPORTED_LOWEST_PRICE_LAST_30_DAYS
            and evidence.currency == offer.currency
            and evidence.reference_window_days == 30
            and evidence.match_method == "direct_retailer_product_id"
            and evidence.source_url == offer.product.product_url
            and evidence.price > 0
        ),
        None,
    )


def _candidate_fingerprint(offer: ProductOffer) -> str:
    return f"m7:v1:{offer.currency.upper()}:{offer.price:.2f}"


def _window(analysis: PriceHistoryAnalysis, days: int) -> WindowStatistics:
    return next(window for window in analysis.windows if window.window_days == days)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")
