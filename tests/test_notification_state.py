from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from dealwatch.discord import DiscordNotificationError, send_test_notification
from dealwatch.models import Availability, NotificationEvent, ProductIdentity, ProductOffer
from dealwatch.notification_state import deliver_once
from dealwatch.storage import SQLiteStore

SENT_AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _product(product_id: str = "1001") -> ProductIdentity:
    return ProductIdentity(
        retailer="x-kom",
        retailer_product_id=product_id,
        category="gpu",
        name=f"Acme GPU {product_id}",
        brand="Acme",
        manufacturer_sku=f"ACME-{product_id}",
        product_url=f"https://www.x-kom.pl/p/{product_id}-acme-gpu.html",
        image_url=None,
    )


def _event(
    *,
    product: ProductIdentity | None = None,
    alert_type: str = "price_drop",
    fingerprint: str = "price-drop:1500",
    observed_price: str = "1500",
) -> NotificationEvent:
    return NotificationEvent(
        product=product or _product(),
        alert_type=alert_type,
        fingerprint=fingerprint,
        reason="The caller identified a price change.",
        observed_price=Decimal(observed_price),
        currency="PLN",
        sent_at=SENT_AT,
        destination_label="discord:dealwatch-test",
    )


def _offer(product: ProductIdentity) -> ProductOffer:
    return ProductOffer(
        product=product,
        price=Decimal("1500"),
        currency="PLN",
        availability=Availability.AVAILABLE,
        previous_price=Decimal("1600"),
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=SENT_AT,
    )


def test_first_alert_is_eligible_and_same_fingerprint_is_already_sent(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "dealwatch.sqlite3")
    event = _event()

    assert not store.has_successful_notification(event)
    assert store.record_successful_notification(event)
    assert store.has_successful_notification(event)
    assert not store.record_successful_notification(event)


def test_fingerprint_defines_equivalence_even_when_alert_type_changes(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "dealwatch.sqlite3")
    first = _event(alert_type="price_drop")
    renamed = _event(alert_type="new_low")

    assert store.record_successful_notification(first)
    assert store.has_successful_notification(renamed)


def test_new_fingerprints_and_prices_are_distinct_alerts_for_one_product(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "dealwatch.sqlite3")
    first = _event(fingerprint="price-drop:1500", observed_price="1500")
    new_price = _event(fingerprint="price-drop:1400", observed_price="1400")

    assert store.record_successful_notification(first)
    assert not store.has_successful_notification(new_price)
    assert store.record_successful_notification(new_price)


def test_notification_state_isolated_between_products(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "dealwatch.sqlite3")
    first_product_event = _event(product=_product("1001"))
    second_product_event = _event(product=_product("1002"))

    assert store.record_successful_notification(first_product_event)
    assert not store.has_successful_notification(second_product_event)
    assert store.record_successful_notification(second_product_event)


def test_failed_discord_delivery_leaves_alert_eligible_for_retry(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "dealwatch.sqlite3")
    event = _event()
    offer = _offer(event.product)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscordNotificationError, match="HTTP 500"):
            deliver_once(
                store,
                event,
                lambda: send_test_notification(client, "https://discord.test/webhook", offer),
            )

    assert not store.has_successful_notification(event)


def test_successful_discord_delivery_records_once_and_retries_are_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "dealwatch.sqlite3"
    store = SQLiteStore(database_path)
    event = _event()
    offer = _offer(event.product)
    delivery_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal delivery_count
        delivery_count += 1
        return httpx.Response(204, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = deliver_once(
            store,
            event,
            lambda: send_test_notification(client, "https://discord.test/webhook", offer),
        )
        second = deliver_once(
            store,
            event,
            lambda: send_test_notification(client, "https://discord.test/webhook", offer),
        )

    assert first.delivered
    assert not first.already_sent
    assert not second.delivered
    assert second.already_sent
    assert delivery_count == 1
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT alert_type, fingerprint, observed_price, currency, destination_label, sent_at
            FROM sent_notifications
            """
        ).fetchall()
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sent_notifications)").fetchall()
        }

    assert rows == [
        (
            "price_drop",
            "price-drop:1500",
            "1500",
            "PLN",
            "discord:dealwatch-test",
            SENT_AT.isoformat(),
        )
    ]
    assert "webhook_url" not in columns


def test_notification_state_preserves_existing_price_history(tmp_path: Path) -> None:
    database_path = tmp_path / "dealwatch.sqlite3"
    store = SQLiteStore(database_path)
    offer = _offer(_product())
    store.record_collection([offer])

    assert store.record_successful_notification(_event(product=offer.product))
    history = store.get_price_history("x-kom", "1001", as_of=SENT_AT)

    assert history is not None
    assert len(history.observations) == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sent_notifications").fetchone()[0] == 1


def test_notification_event_rejects_a_webhook_url_as_a_destination_label() -> None:
    with pytest.raises(ValueError, match="non-secret label"):
        NotificationEvent(
            product=_product(),
            alert_type="price_drop",
            fingerprint="price-drop:1500",
            sent_at=SENT_AT,
            destination_label="https://discord.com/api/webhooks/secret",
        )
