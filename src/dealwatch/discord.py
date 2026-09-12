"""Discord webhook delivery for explicit MVP test notifications."""

from __future__ import annotations

from decimal import Decimal

import httpx

from dealwatch.deals import DealCandidate
from dealwatch.models import Availability, ProductOffer


class DiscordNotificationError(RuntimeError):
    """Raised when Discord cannot accept a test notification."""


def send_test_notification(
    client: httpx.Client,
    webhook_url: str,
    offer: ProductOffer,
) -> None:
    """Send a single operator-selected, in-stock product to Discord."""

    if offer.availability is not Availability.AVAILABLE:
        raise DiscordNotificationError(
            f"Product {offer.product.retailer_product_id} is not currently available"
        )

    _post_webhook(client, webhook_url, _payload(offer))


def send_deal_notification(
    client: httpx.Client,
    webhook_url: str,
    offer: ProductOffer,
    candidate: DealCandidate,
) -> None:
    """Deliver one rule-qualified candidate without using retailer promotion labels."""

    if offer.availability is not Availability.AVAILABLE:
        raise DiscordNotificationError(
            f"Product {offer.product.retailer_product_id} is not currently available"
        )

    _post_webhook(client, webhook_url, _candidate_payload(offer, candidate))


def _post_webhook(
    client: httpx.Client, webhook_url: str, payload: dict[str, object]
) -> None:
    try:
        response = client.post(webhook_url, json=payload)
    except httpx.RequestError as error:
        raise DiscordNotificationError("Discord webhook request failed") from error
    _raise_for_delivery_failure(response)


def _raise_for_delivery_failure(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise DiscordNotificationError(
            f"Discord webhook returned HTTP {response.status_code}"
        ) from error


def _payload(offer: ProductOffer) -> dict[str, object]:
    fields = [
        {"name": "Price", "value": _format_price(offer.price, offer.currency), "inline": True},
        {"name": "Retailer", "value": offer.product.retailer, "inline": True},
    ]
    if offer.previous_price is not None:
        fields.append(
            {
                "name": "Previous price",
                "value": _format_price(offer.previous_price, offer.currency),
                "inline": True,
            }
        )
    if offer.promotion_labels:
        fields.append(
            {
                "name": "Promotions",
                "value": ", ".join(offer.promotion_labels),
                "inline": False,
            }
        )

    embed: dict[str, object] = {
        "title": offer.product.name,
        "url": offer.product.product_url,
        "description": "Manual DealWatch PL Discord delivery test.",
        "fields": fields,
        "footer": {"text": f"Product ID: {offer.product.retailer_product_id}"},
    }
    if offer.product.image_url:
        embed["thumbnail"] = {"url": offer.product.image_url}
    return {
        "username": "DealWatch PL",
        "allowed_mentions": {"parse": []},
        "embeds": [embed],
    }


def _candidate_payload(offer: ProductOffer, candidate: DealCandidate) -> dict[str, object]:
    reasons = "\n".join(
        (
            f"{signal.signal_type.value}: "
            f"{signal.percentage_savings:.2f}% / {signal.absolute_savings:.2f} {candidate.currency}"
        )
        for signal in candidate.signals
    )
    fields = [
        {
            "name": "Price",
            "value": _format_price(candidate.price, candidate.currency),
            "inline": True,
        },
        {"name": "History", "value": candidate.history_baseline.value, "inline": True},
        {"name": "Why", "value": reasons, "inline": False},
    ]
    embed: dict[str, object] = {
        "title": offer.product.name,
        "url": offer.product.product_url,
        "description": "DealWatch PL rule-based deal candidate.",
        "fields": fields,
        "footer": {"text": f"Product ID: {offer.product.retailer_product_id}"},
    }
    if offer.product.image_url:
        embed["thumbnail"] = {"url": offer.product.image_url}
    return {
        "username": "DealWatch PL",
        "allowed_mentions": {"parse": []},
        "embeds": [embed],
    }


def _format_price(value: Decimal, currency: str) -> str:
    return f"{value:.2f} {currency}"
