from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from dealwatch.deals import DealCandidate, DealSignal, DealSignalType, HistoryBaseline
from dealwatch.discord import (
    DiscordNotificationError,
    send_deal_notification,
    send_test_notification,
)
from dealwatch.models import Availability, ProductIdentity, ProductOffer


def _offer(*, availability: Availability = Availability.AVAILABLE) -> ProductOffer:
    return ProductOffer(
        product=ProductIdentity(
            retailer="x-kom",
            retailer_product_id="1002",
            category="gpu",
            name="Best Discount GPU",
            brand="Best Brand",
            manufacturer_sku="BEST-1002",
            product_url="https://www.x-kom.pl/p/1002-best-gpu.html",
            image_url="https://cdn.example/1002.jpg",
        ),
        price=Decimal("2499.99"),
        currency="PLN",
        availability=availability,
        previous_price=Decimal("2999.99"),
        reported_minimum_price=None,
        promotion_labels=("Autumn sale",),
        observed_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
    )


def test_sends_compact_discord_embed() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(204, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        send_test_notification(client, "https://discord.test/webhook", _offer())

    assert payloads[0]["allowed_mentions"] == {"parse": []}
    embed = payloads[0]["embeds"][0]
    assert embed["title"] == "Best Discount GPU"
    assert embed["url"] == "https://www.x-kom.pl/p/1002-best-gpu.html"
    assert {field["name"]: field["value"] for field in embed["fields"]}["Price"] == "2499.99 PLN"


def test_rejects_unavailable_product_without_posting() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Discord must not be called")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscordNotificationError, match="not currently available"):
            send_test_notification(
                client,
                "https://discord.test/webhook",
                _offer(availability=Availability.OUT_OF_STOCK),
            )


def test_wraps_discord_http_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscordNotificationError, match="HTTP 400"):
            send_test_notification(client, "https://discord.test/webhook", _offer())


def test_wraps_discord_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscordNotificationError, match="request failed"):
            send_test_notification(client, "https://discord.test/webhook", _offer())


def test_sends_candidate_embed_with_history_and_evidence_but_no_promotion_labels() -> None:
    payloads: list[dict[str, object]] = []
    offer = _offer()
    candidate = DealCandidate(
        product=offer.product,
        price=offer.price,
        currency=offer.currency,
        observed_at=offer.observed_at,
        history_baseline=HistoryBaseline.SUFFICIENT_7D,
        signals=(
            DealSignal(
                signal_type=DealSignalType.BELOW_7_DAY_MEDIAN,
                reference_price=Decimal("2800"),
                absolute_savings=Decimal("300.01"),
                percentage_savings=Decimal("10.71"),
                qualifies=True,
            ),
        ),
        fingerprint="m7:v1:PLN:2499.99",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(204, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        send_deal_notification(client, "https://discord.test/webhook", offer, candidate)

    embed = payloads[0]["embeds"][0]
    fields = {field["name"]: field["value"] for field in embed["fields"]}
    assert embed["description"] == "DealWatch PL rule-based deal candidate."
    assert fields["Price"] == "2499.99 PLN"
    assert fields["History"] == "sufficient_7d"
    assert "below_7_day_median" in fields["Why"]
    assert "Promotions" not in fields
    assert "Autumn sale" not in json.dumps(payloads[0])
