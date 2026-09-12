"""Retailer-neutral product and offer value objects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class Availability(StrEnum):
    """Normalized availability reported by a retailer."""

    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    """Stable retailer product identity, intentionally excluding its price."""

    retailer: str
    retailer_product_id: str
    category: str
    name: str
    brand: str | None
    manufacturer_sku: str | None
    product_url: str
    image_url: str | None


@dataclass(frozen=True, slots=True)
class ProductOffer:
    """An observed commercial offer for a stable product identity."""

    product: ProductIdentity
    price: Decimal
    currency: str
    availability: Availability
    previous_price: Decimal | None
    reported_minimum_price: Decimal | None
    promotion_labels: tuple[str, ...]
    observed_at: datetime

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe data without converting currency values to floats."""

        data = asdict(self)
        product = data["product"]
        assert isinstance(product, dict)
        return {
            "product": product,
            "price": format(self.price, "f"),
            "currency": self.currency,
            "availability": self.availability.value,
            "previous_price": _decimal_to_string(self.previous_price),
            "reported_minimum_price": _decimal_to_string(self.reported_minimum_price),
            "promotion_labels": list(self.promotion_labels),
            "observed_at": self.observed_at.isoformat(),
        }


def _decimal_to_string(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One persisted price observation used by history and future deal logic."""

    current_price: Decimal
    currency: str
    old_price: Decimal | None
    availability: Availability
    observed_at: datetime

    def to_dict(self) -> dict[str, str | None]:
        return {
            "current_price": format(self.current_price, "f"),
            "currency": self.currency,
            "old_price": _decimal_to_string(self.old_price),
            "availability": self.availability.value,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    """A caller-defined alert that was successfully delivered to a destination."""

    product: ProductIdentity
    alert_type: str
    fingerprint: str
    sent_at: datetime
    reason: str | None = None
    observed_price: Decimal | None = None
    currency: str | None = None
    destination_label: str | None = None

    def __post_init__(self) -> None:
        if not self.alert_type.strip():
            raise ValueError("alert_type must not be empty")
        if not self.fingerprint.strip():
            raise ValueError("fingerprint must not be empty")
        if self.observed_price is not None and not self.currency:
            raise ValueError("currency is required when observed_price is set")
        if self.destination_label and "://" in self.destination_label:
            raise ValueError("destination_label must be a non-secret label, not a URL")
