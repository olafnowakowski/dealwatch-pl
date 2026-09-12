"""One-shot orchestration for safe candidate delivery."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from dealwatch.deals import DealCandidate, evaluate_deal
from dealwatch.discord import DiscordNotificationError, send_deal_notification
from dealwatch.models import NotificationEvent, ProductOffer
from dealwatch.notification_state import deliver_once
from dealwatch.storage import PersistenceError, SQLiteStore

MAX_ELIGIBLE_CANDIDATES = 3


@dataclass(frozen=True, slots=True)
class MonitoringCandidate:
    """A candidate and the offer used to render a potential delivery."""

    offer: ProductOffer
    candidate: DealCandidate
    already_sent: bool

    def to_dict(self) -> dict[str, object]:
        data = self.candidate.to_dict()
        data["already_notified"] = self.already_sent
        data["notification_eligible"] = not self.already_sent
        return data


@dataclass(frozen=True, slots=True)
class MonitoringFailure:
    """A safe, operator-visible description of one failed candidate delivery."""

    product_id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"product_id": self.product_id, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class MonitoringSummary:
    """Outcome and safety state of one complete monitoring run."""

    collected_count: int
    evaluated_count: int
    history_baseline_counts: dict[str, int]
    candidate_signal_counts: dict[str, int]
    candidates: tuple[MonitoringCandidate, ...]
    eligible_count: int
    selected_for_delivery_count: int
    delivered_count: int
    failures: tuple[MonitoringFailure, ...]
    circuit_breaker_triggered: bool
    send_enabled: bool

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def already_sent_count(self) -> int:
        return sum(candidate.already_sent for candidate in self.candidates)

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def failed_product_ids(self) -> tuple[str, ...]:
        return tuple(failure.product_id for failure in self.failures)

    @property
    def is_successful(self) -> bool:
        return not self.circuit_breaker_triggered and self.failed_count == 0

    def to_dict(self, *, include_candidates: bool = True) -> dict[str, object]:
        data: dict[str, object] = {
            "mode": "send" if self.send_enabled else "dry_run",
            "collected_count": self.collected_count,
            "evaluated_count": self.evaluated_count,
            "history_baseline_counts": self.history_baseline_counts,
            "candidate_count": self.candidate_count,
            "candidate_signal_counts": self.candidate_signal_counts,
            "already_sent_count": self.already_sent_count,
            "eligible_count": self.eligible_count,
            "selected_for_delivery_count": self.selected_for_delivery_count,
            "delivered_count": self.delivered_count,
            "failed_count": self.failed_count,
            "failed_product_ids": list(self.failed_product_ids),
            "failures": [failure.to_dict() for failure in self.failures],
            "circuit_breaker": {
                "limit": MAX_ELIGIBLE_CANDIDATES,
                "triggered": self.circuit_breaker_triggered,
            },
        }
        if include_candidates:
            data["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return data


def monitor_offers(
    store: SQLiteStore,
    offers: list[ProductOffer],
    *,
    send_enabled: bool,
    webhook_url: str | None = None,
    only_product_id: str | None = None,
    discord_client: httpx.Client | None = None,
) -> MonitoringSummary:
    """Evaluate persisted offers and optionally deliver their unseen candidates.

    This function does not collect or schedule. Failed deliveries are deliberately not
    retried here because a timed-out webhook request has ambiguous delivery state.
    """

    records, baseline_counts = _candidate_records(store, offers)
    eligible = [record for record in records if not record.already_sent]
    circuit_breaker_triggered = len(eligible) > MAX_ELIGIBLE_CANDIDATES
    if not send_enabled or circuit_breaker_triggered:
        return _summary(
            offers,
            records,
            baseline_counts,
            eligible_count=len(eligible),
            selected_count=0,
            delivered_count=0,
            failures=(),
            circuit_breaker_triggered=circuit_breaker_triggered,
            send_enabled=send_enabled,
        )

    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URL must be set when --send is used")
    if discord_client is None:
        raise ValueError("discord_client is required when --send is used")

    selected = [
        record
        for record in eligible
        if only_product_id is None or record.offer.product.retailer_product_id == only_product_id
    ]
    delivered_count = 0
    failures: list[MonitoringFailure] = []
    destination_label = _destination_label(webhook_url)
    for record in selected:
        event = NotificationEvent(
            product=record.candidate.product,
            alert_type=record.candidate.alert_type,
            fingerprint=record.candidate.fingerprint,
            reason=record.candidate.explanation,
            observed_price=record.candidate.price,
            currency=record.candidate.currency,
            sent_at=datetime.now(UTC),
            destination_label=destination_label,
        )
        transport_accepted = [False]

        def deliver_candidate(
            offer: ProductOffer = record.offer,
            candidate: DealCandidate = record.candidate,
            accepted: list[bool] = transport_accepted,
        ) -> None:
            send_deal_notification(
                discord_client,
                webhook_url,
                offer,
                candidate,
            )
            accepted[0] = True

        try:
            result = deliver_once(store, event, deliver_candidate)
        except DiscordNotificationError:
            failures.append(
                MonitoringFailure(
                    product_id=record.offer.product.retailer_product_id,
                    reason=(
                        "Discord delivery failed; the candidate remains eligible for a later run."
                    ),
                )
            )
            continue
        except PersistenceError:
            reason = (
                "Discord delivery may have succeeded, but notification state could not be "
                "persisted; "
                "the next run may duplicate this alert."
                if transport_accepted[0]
                else "Notification state could not be read before Discord delivery."
            )
            failures.append(
                MonitoringFailure(
                    product_id=record.offer.product.retailer_product_id,
                    reason=reason,
                )
            )
            continue
        if result.delivered:
            delivered_count += 1

    return _summary(
        offers,
        records,
        baseline_counts,
        eligible_count=len(eligible),
        selected_count=len(selected),
        delivered_count=delivered_count,
        failures=tuple(failures),
        circuit_breaker_triggered=False,
        send_enabled=True,
    )


def _candidate_records(
    store: SQLiteStore,
    offers: list[ProductOffer],
) -> tuple[list[MonitoringCandidate], dict[str, int]]:
    records: list[MonitoringCandidate] = []
    baseline_counts: Counter[str] = Counter()
    for offer in offers:
        history = store.get_price_history(
            offer.product.retailer,
            offer.product.retailer_product_id,
            as_of=offer.observed_at,
        )
        if history is None:
            raise PersistenceError(
                f"Persisted x-kom product {offer.product.retailer_product_id} could not be read"
            )
        evaluation = evaluate_deal(offer, history)
        baseline_counts[evaluation.history_baseline.value] += 1
        if evaluation.candidate is None:
            continue
        records.append(
            MonitoringCandidate(
                offer=offer,
                candidate=evaluation.candidate,
                already_sent=store.has_successful_notification_for(
                    evaluation.candidate.product,
                    evaluation.candidate.fingerprint,
                ),
            )
        )
    return records, dict(baseline_counts)


def _summary(
    offers: list[ProductOffer],
    records: list[MonitoringCandidate],
    baseline_counts: dict[str, int],
    *,
    eligible_count: int,
    selected_count: int,
    delivered_count: int,
    failures: tuple[MonitoringFailure, ...],
    circuit_breaker_triggered: bool,
    send_enabled: bool,
) -> MonitoringSummary:
    signal_counts: Counter[str] = Counter()
    for record in records:
        signal_counts.update(signal.signal_type.value for signal in record.candidate.signals)
    return MonitoringSummary(
        collected_count=len(offers),
        evaluated_count=len(offers),
        history_baseline_counts=baseline_counts,
        candidate_signal_counts=dict(signal_counts),
        candidates=tuple(records),
        eligible_count=eligible_count,
        selected_for_delivery_count=selected_count,
        delivered_count=delivered_count,
        failures=failures,
        circuit_breaker_triggered=circuit_breaker_triggered,
        send_enabled=send_enabled,
    )


def _destination_label(webhook_url: str) -> str:
    digest = hashlib.sha256(webhook_url.encode("utf-8")).hexdigest()[:16]
    return f"discord:webhook:{digest}"
