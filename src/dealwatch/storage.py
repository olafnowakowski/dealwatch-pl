"""Minimal SQLite persistence for product identities and price observations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dealwatch.models import ProductOffer

DEFAULT_DATABASE_PATH = Path("data/dealwatch.sqlite3")


class PersistenceError(RuntimeError):
    """Raised when a collection cannot be persisted safely."""


@dataclass(frozen=True, slots=True)
class StoredProduct:
    """Product metadata retained by the local SQLite store."""

    retailer: str
    retailer_product_id: str
    category: str
    name: str
    product_url: str

    def to_dict(self) -> dict[str, str]:
        return {
            "retailer": self.retailer,
            "retailer_product_id": self.retailer_product_id,
            "category": self.category,
            "name": self.name,
            "product_url": self.product_url,
        }


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One stored price observation for a product."""

    current_price: Decimal
    currency: str
    old_price: Decimal | None
    availability: str
    observed_at: datetime

    def to_dict(self) -> dict[str, str | None]:
        return {
            "current_price": format(self.current_price, "f"),
            "currency": self.currency,
            "old_price": _decimal_text(self.old_price),
            "availability": self.availability,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ProductPriceHistory:
    """Read-only product history and low-price summaries."""

    product: StoredProduct
    observations: tuple[PriceObservation, ...]
    recent_window_days: int
    as_of: datetime

    @property
    def current_observation(self) -> PriceObservation | None:
        return self.observations[-1] if self.observations else None

    @property
    def previous_observation(self) -> PriceObservation | None:
        return self.observations[-2] if len(self.observations) > 1 else None

    @property
    def all_time_low(self) -> PriceObservation | None:
        return _lowest_available(self.observations)

    @property
    def recent_minimum(self) -> PriceObservation | None:
        cutoff = self.as_of - timedelta(days=self.recent_window_days)
        return _lowest_available(
            observation for observation in self.observations if observation.observed_at >= cutoff
        )

    def to_dict(self) -> dict[str, object]:
        current = self.current_observation
        previous = self.previous_observation
        first = self.observations[0] if self.observations else None
        return {
            "product": self.product.to_dict(),
            "observations": [observation.to_dict() for observation in self.observations],
            "summary": {
                "observation_count": len(self.observations),
                "available_observation_count": sum(
                    observation.availability == "available" for observation in self.observations
                ),
                "first_observed_at": first.observed_at.isoformat() if first else None,
                "last_observed_at": current.observed_at.isoformat() if current else None,
                "current_observation": current.to_dict() if current else None,
                "previous_observation": previous.to_dict() if previous else None,
                "all_time_low": self.all_time_low.to_dict() if self.all_time_low else None,
                "recent_window_days": self.recent_window_days,
                "recent_window_start": (
                    self.as_of - timedelta(days=self.recent_window_days)
                ).isoformat(),
                "recent_minimum": self.recent_minimum.to_dict() if self.recent_minimum else None,
            },
        }


class SQLiteStore:
    """Store stable product identities separately from append-only price observations."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def record_collection(self, offers: list[ProductOffer]) -> int:
        """Upsert products and append one observation for every collected offer."""

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                self._create_schema(connection)
                for offer in offers:
                    product_id = self._upsert_product(connection, offer)
                    connection.execute(
                        """
                        INSERT INTO price_observations (
                            product_id,
                            current_price,
                            currency,
                            old_price,
                            availability,
                            observed_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            product_id,
                            format(offer.price, "f"),
                            offer.currency,
                            _decimal_text(offer.previous_price),
                            offer.availability.value,
                            offer.observed_at.isoformat(),
                        ),
                    )
        except (OSError, sqlite3.Error) as error:
            message = f"Could not persist collection to {self._database_path}: {error}"
            raise PersistenceError(message) from error
        return len(offers)

    def get_price_history(
        self,
        retailer: str,
        retailer_product_id: str,
        *,
        recent_window_days: int = 30,
        as_of: datetime | None = None,
    ) -> ProductPriceHistory | None:
        """Return ordered observations and summaries for one stored product."""

        if recent_window_days <= 0:
            raise ValueError("recent_window_days must be positive")
        as_of_utc = _as_utc(as_of or datetime.now(UTC))
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                self._create_schema(connection)
                product_row = connection.execute(
                    """
                    SELECT retailer, retailer_product_id, category, name, product_url, id
                    FROM products
                    WHERE retailer = ? AND retailer_product_id = ?
                    """,
                    (retailer, retailer_product_id),
                ).fetchone()
                if product_row is None:
                    return None
                observation_rows = connection.execute(
                    """
                    SELECT current_price, currency, old_price, availability, observed_at
                    FROM price_observations
                    WHERE product_id = ?
                    ORDER BY observed_at, id
                    """,
                    (product_row[5],),
                ).fetchall()
        except (OSError, sqlite3.Error) as error:
            message = f"Could not read price history from {self._database_path}: {error}"
            raise PersistenceError(message) from error

        product = StoredProduct(
            retailer=product_row[0],
            retailer_product_id=product_row[1],
            category=product_row[2],
            name=product_row[3],
            product_url=product_row[4],
        )
        observations = tuple(_observation_from_row(row) for row in observation_rows)
        return ProductPriceHistory(
            product=product,
            observations=observations,
            recent_window_days=recent_window_days,
            as_of=as_of_utc,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                retailer TEXT NOT NULL,
                retailer_product_id TEXT NOT NULL,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                product_url TEXT NOT NULL,
                UNIQUE (retailer, retailer_product_id)
            );

            CREATE TABLE IF NOT EXISTS price_observations (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id),
                current_price TEXT NOT NULL,
                currency TEXT NOT NULL,
                old_price TEXT,
                availability TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_price_observations_product_observed_at
            ON price_observations (product_id, observed_at);
            """
        )

    @staticmethod
    def _upsert_product(connection: sqlite3.Connection, offer: ProductOffer) -> int:
        product = offer.product
        connection.execute(
            """
            INSERT INTO products (
                retailer,
                retailer_product_id,
                category,
                name,
                product_url
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(retailer, retailer_product_id) DO UPDATE SET
                category = excluded.category,
                name = excluded.name,
                product_url = excluded.product_url
            """,
            (
                product.retailer,
                product.retailer_product_id,
                product.category,
                product.name,
                product.product_url,
            ),
        )
        row = connection.execute(
            """
            SELECT id FROM products
            WHERE retailer = ? AND retailer_product_id = ?
            """,
            (product.retailer, product.retailer_product_id),
        ).fetchone()
        if row is None:
            raise PersistenceError("Persisted product could not be read back")
        return int(row[0])


def _decimal_text(value: object) -> str | None:
    return format(value, "f") if value is not None else None


def _observation_from_row(row: tuple[str, str, str | None, str, str]) -> PriceObservation:
    try:
        observed_at = _as_utc(datetime.fromisoformat(row[4]))
        return PriceObservation(
            current_price=Decimal(row[0]),
            currency=row[1],
            old_price=Decimal(row[2]) if row[2] is not None else None,
            availability=row[3],
            observed_at=observed_at,
        )
    except (InvalidOperation, ValueError) as error:
        raise PersistenceError("Stored price observation has invalid data") from error


def _lowest_available(observations: Iterable[PriceObservation]) -> PriceObservation | None:
    available = [
        observation
        for observation in observations
        if observation.availability == "available"
    ]
    if not available:
        return None
    return min(
        available,
        key=lambda observation: (observation.current_price, observation.observed_at),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
