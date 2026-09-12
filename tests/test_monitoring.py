from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from dealwatch.deals import DEFAULT_DEAL_RULES
from dealwatch.models import (
    Availability,
    ProductIdentity,
    ProductOffer,
    ReferencePriceEvidence,
    ReferencePriceKind,
    ReferencePriceScope,
)
from dealwatch.monitoring import MAX_ELIGIBLE_CANDIDATES, monitor_offers
from dealwatch.storage import SQLiteStore

OBSERVED_AT = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
WEBHOOK_URL = "https://discord.test/webhook/secret"


def _offer(product_id: str, *, price: str = "1800") -> ProductOffer:
    return ProductOffer(
        product=ProductIdentity(
            retailer="x-kom",
            retailer_product_id=product_id,
            category="gpu",
            name=f"Acme GPU {product_id}",
            brand="Acme",
            manufacturer_sku=f"ACME-{product_id}",
            product_url=f"https://www.x-kom.pl/p/{product_id}-acme-gpu.html",
            image_url=None,
        ),
        price=Decimal(price),
        currency="PLN",
        availability=Availability.AVAILABLE,
        previous_price=Decimal("2000"),
        reported_minimum_price=None,
        promotion_labels=("Retailer promotion",),
        observed_at=OBSERVED_AT,
    )


def _xkom_reference(offer: ProductOffer, price: str) -> ReferencePriceEvidence:
    return ReferencePriceEvidence(
        source="x-kom",
        scope=ReferencePriceScope.RETAILER,
        kind=ReferencePriceKind.XCOM_REPORTED_LOWEST_PRICE_LAST_30_DAYS,
        price=Decimal(price),
        currency="PLN",
        reference_window_days=30,
        source_url=offer.product.product_url,
        match_method="direct_retailer_product_id",
        first_seen_at=offer.observed_at,
        last_seen_at=offer.observed_at,
    )


def _persist_candidate_history(store: SQLiteStore, offer: ProductOffer) -> None:
    store.record_collection(
        [
            replace(
                offer,
                price=Decimal("2000"),
                previous_price=None,
                observed_at=OBSERVED_AT - timedelta(days=8) + timedelta(hours=hour),
            )
            for hour in range(8 * 24)
        ]
    )
    store.record_collection([offer])


def _store_with_candidates(
    tmp_path: Path, product_ids: list[str]
) -> tuple[SQLiteStore, list[ProductOffer]]:
    store = SQLiteStore(tmp_path / "dealwatch.sqlite3")
    offers = [_offer(product_id) for product_id in product_ids]
    for offer in offers:
        _persist_candidate_history(store, offer)
    return store, offers


def test_dry_run_does_not_send_or_record_notification_state_and_counts_signals(
    tmp_path: Path,
) -> None:
    store, offers = _store_with_candidates(tmp_path, ["1001"])

    summary = monitor_offers(store, offers, send_enabled=False)

    assert summary.is_successful
    assert summary.candidate_count == 1
    assert summary.delivered_count == 0
    assert summary.eligible_count == 1
    assert summary.history_baseline_counts == {"sufficient_7d": 1}
    assert summary.candidate_signal_counts == {
        "below_7_day_median": 1,
        "new_all_time_low": 1,
        "retailer_old_price_support": 1,
    }
    with sqlite3.connect(tmp_path / "dealwatch.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM sent_notifications").fetchone()[0] == 0


def test_reference_bootstrap_is_opt_in_and_reported_in_dry_run(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "dealwatch.sqlite3")
    offer = _offer("1001")
    offer = replace(
        offer,
        previous_price=None,
        reference_price_evidence=(_xkom_reference(offer, "2000"),),
    )
    store.record_collection([offer])

    default_summary = monitor_offers(store, [offer], send_enabled=False)
    enabled_summary = monitor_offers(
        store,
        [offer],
        send_enabled=False,
        deal_rules=replace(DEFAULT_DEAL_RULES, enable_xkom_reference_bootstrap=True),
    )

    assert default_summary.candidate_count == 0
    assert default_summary.usable_xkom_reference_count == 1
    assert default_summary.reference_bootstrap_candidate_count == 0
    assert enabled_summary.is_successful
    assert enabled_summary.candidate_count == 1
    assert enabled_summary.usable_xkom_reference_count == 1
    assert enabled_summary.reference_bootstrap_candidate_count == 1
    assert enabled_summary.candidate_signal_counts == {
        "below_xkom_reported_30d_minimum": 1
    }
    assert enabled_summary.candidates[0].created_by_reference_bootstrap
    assert not enabled_summary.circuit_breaker_triggered
    with sqlite3.connect(tmp_path / "dealwatch.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM sent_notifications").fetchone()[0] == 0


def test_reference_bootstrap_candidates_still_trip_the_global_circuit_breaker(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "dealwatch.sqlite3")
    offers = []
    for index in range(MAX_ELIGIBLE_CANDIDATES + 1):
        offer = replace(_offer(str(1001 + index)), previous_price=None)
        offers.append(
            replace(
                offer,
                reference_price_evidence=(_xkom_reference(offer, "2000"),),
            )
        )
    store.record_collection(offers)

    summary = monitor_offers(
        store,
        offers,
        send_enabled=False,
        deal_rules=replace(DEFAULT_DEAL_RULES, enable_xkom_reference_bootstrap=True),
    )

    assert summary.circuit_breaker_triggered
    assert summary.candidate_count == MAX_ELIGIBLE_CANDIDATES + 1
    assert summary.reference_bootstrap_candidate_count == MAX_ELIGIBLE_CANDIDATES + 1
    assert summary.eligible_count == MAX_ELIGIBLE_CANDIDATES + 1
    assert summary.delivered_count == 0


def test_successful_delivery_is_idempotent_and_stores_a_non_secret_destination_label(
    tmp_path: Path,
) -> None:
    store, offers = _store_with_candidates(tmp_path, ["1001"])
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(204, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = monitor_offers(
            store,
            offers,
            send_enabled=True,
            webhook_url=WEBHOOK_URL,
            discord_client=client,
        )
        second = monitor_offers(
            store,
            offers,
            send_enabled=True,
            webhook_url=WEBHOOK_URL,
            discord_client=client,
        )

    assert first.is_successful
    assert first.delivered_count == 1
    assert second.is_successful
    assert second.already_sent_count == 1
    assert second.eligible_count == 0
    assert second.delivered_count == 0
    assert calls == 1
    with sqlite3.connect(tmp_path / "dealwatch.sqlite3") as connection:
        destination_label = connection.execute(
            "SELECT destination_label FROM sent_notifications"
        ).fetchone()[0]
    assert destination_label.startswith("discord:webhook:")
    assert WEBHOOK_URL not in destination_label


def test_failed_delivery_continues_later_candidates_and_remains_retry_eligible(
    tmp_path: Path,
) -> None:
    store, offers = _store_with_candidates(tmp_path, ["1001", "1002"])
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        status_code = 500 if calls == 1 else 204
        return httpx.Response(status_code, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = monitor_offers(
            store,
            offers,
            send_enabled=True,
            webhook_url=WEBHOOK_URL,
            discord_client=client,
        )

    assert not summary.is_successful
    assert summary.failed_product_ids == ("1001",)
    assert summary.delivered_count == 1
    assert store.has_successful_notification_for(
        offers[1].product, "m7:v1:PLN:1800.00"
    )
    assert not store.has_successful_notification_for(
        offers[0].product, "m7:v1:PLN:1800.00"
    )


def test_circuit_breaker_blocks_every_delivery_even_with_only_product_selection(
    tmp_path: Path,
) -> None:
    product_ids = [str(1001 + index) for index in range(MAX_ELIGIBLE_CANDIDATES + 1)]
    store, offers = _store_with_candidates(tmp_path, product_ids)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("breaker must prevent every Discord request")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = monitor_offers(
            store,
            offers,
            send_enabled=True,
            webhook_url=WEBHOOK_URL,
            only_product_id=offers[0].product.retailer_product_id,
            discord_client=client,
        )

    assert summary.circuit_breaker_triggered
    assert not summary.is_successful
    assert summary.eligible_count == MAX_ELIGIBLE_CANDIDATES + 1
    assert summary.selected_for_delivery_count == 0
    assert summary.delivered_count == 0
    with sqlite3.connect(tmp_path / "dealwatch.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM sent_notifications").fetchone()[0] == 0


def test_send_requires_webhook_configuration_without_recording_state(tmp_path: Path) -> None:
    store, offers = _store_with_candidates(tmp_path, ["1001"])

    with pytest.raises(ValueError, match="DISCORD_WEBHOOK_URL"):
        monitor_offers(store, offers, send_enabled=True)

    assert not store.has_successful_notification_for(offers[0].product, "m7:v1:PLN:1800.00")


def test_only_product_limits_delivery_after_global_eligibility_check(tmp_path: Path) -> None:
    store, offers = _store_with_candidates(tmp_path, ["1001", "1002"])
    delivered_titles: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        delivered_titles.append(request.content.decode("utf-8"))
        return httpx.Response(204, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = monitor_offers(
            store,
            offers,
            send_enabled=True,
            webhook_url=WEBHOOK_URL,
            only_product_id="1002",
            discord_client=client,
        )

    assert summary.is_successful
    assert summary.eligible_count == 2
    assert summary.selected_for_delivery_count == 1
    assert summary.delivered_count == 1
    assert len(delivered_titles) == 1
    assert store.has_successful_notification_for(offers[1].product, "m7:v1:PLN:1800.00")
    assert not store.has_successful_notification_for(offers[0].product, "m7:v1:PLN:1800.00")
