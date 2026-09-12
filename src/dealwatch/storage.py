"""Minimal SQLite persistence for product identities and price observations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dealwatch.history import PriceHistoryAnalysis, analyze_price_history
from dealwatch.models import (
    Availability,
    NotificationEvent,
    PriceObservation,
    ProductIdentity,
    ProductOffer,
    ReferencePriceEvidence,
    ReferencePriceKind,
    ReferencePriceScope,
)

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

    @property
    def analysis(self) -> PriceHistoryAnalysis:
        """Return reusable, coverage-aware history metrics for this product."""

        return analyze_price_history(self.observations, as_of=self.as_of)

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
                    observation.availability is Availability.AVAILABLE
                    for observation in self.observations
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
            "analysis": self.analysis.to_dict(),
        }


class SQLiteStore:
    """Store stable product identities separately from append-only price observations."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def record_collection(self, offers: list[ProductOffer]) -> int:
        """Upsert products and append one observation for every collected offer."""

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._transaction() as connection:
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
                    for evidence in offer.reference_price_evidence:
                        self._record_reference_price_evidence(
                            connection,
                            product_id,
                            evidence,
                            seen_at=_as_utc(offer.observed_at),
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
            with self._transaction() as connection:
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

    def get_reference_price_evidence(
        self,
        retailer: str,
        retailer_product_id: str,
    ) -> tuple[ReferencePriceEvidence, ...]:
        """Return source-attributed evidence episodes without reading native prices."""

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._transaction() as connection:
                self._create_schema(connection)
                rows = connection.execute(
                    """
                    SELECT evidence.source, evidence.scope, evidence.reference_kind,
                           evidence.reference_price, evidence.currency,
                           evidence.reference_window_days, evidence.source_url,
                           evidence.match_method, evidence.first_seen_at, evidence.last_seen_at
                    FROM reference_price_evidence AS evidence
                    JOIN products AS product ON product.id = evidence.product_id
                    WHERE product.retailer = ? AND product.retailer_product_id = ?
                    ORDER BY evidence.id
                    """,
                    (retailer, retailer_product_id),
                ).fetchall()
        except (OSError, sqlite3.Error) as error:
            message = f"Could not read reference evidence from {self._database_path}: {error}"
            raise PersistenceError(message) from error
        return tuple(_reference_evidence_from_row(row) for row in rows)

    def has_successful_notification(self, event: NotificationEvent) -> bool:
        """Return whether this caller-defined alert was previously delivered."""

        return self.has_successful_notification_for(event.product, event.fingerprint)

    def has_successful_notification_for(
        self,
        product: ProductIdentity,
        fingerprint: str,
    ) -> bool:
        """Return whether a product-specific candidate fingerprint was delivered."""

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._transaction() as connection:
                self._create_schema(connection)
                row = connection.execute(
                    """
                    SELECT 1
                    FROM sent_notifications AS notification
                    JOIN products AS product ON product.id = notification.product_id
                    WHERE product.retailer = ?
                      AND product.retailer_product_id = ?
                      AND notification.fingerprint = ?
                    """,
                    (
                        product.retailer,
                        product.retailer_product_id,
                        fingerprint,
                    ),
                ).fetchone()
        except (OSError, sqlite3.Error) as error:
            message = f"Could not read notification state from {self._database_path}: {error}"
            raise PersistenceError(message) from error
        return row is not None

    def record_successful_notification(self, event: NotificationEvent) -> bool:
        """Record one delivered alert, returning false if its fingerprint already exists.

        Call this only after the transport reports success. The unique key makes a
        completed notification idempotent without defining any alert or cooldown policy.
        """

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._transaction() as connection:
                self._create_schema(connection)
                product_id = self._upsert_product_identity(connection, event.product)
                cursor = connection.execute(
                    """
                    INSERT INTO sent_notifications (
                        product_id,
                        alert_type,
                        fingerprint,
                        reason,
                        observed_price,
                        currency,
                        destination_label,
                        sent_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_id, fingerprint) DO NOTHING
                    """,
                    (
                        product_id,
                        event.alert_type,
                        event.fingerprint,
                        event.reason,
                        _decimal_text(event.observed_price),
                        event.currency,
                        event.destination_label,
                        _as_utc(event.sent_at).isoformat(),
                    ),
                )
        except (OSError, sqlite3.Error) as error:
            message = f"Could not persist notification state to {self._database_path}: {error}"
            raise PersistenceError(message) from error
        return cursor.rowcount == 1

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit or roll back a SQLite operation and close its connection."""

        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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

            CREATE TABLE IF NOT EXISTS reference_price_evidence (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id),
                source TEXT NOT NULL,
                scope TEXT NOT NULL,
                reference_kind TEXT NOT NULL,
                reference_price TEXT NOT NULL,
                currency TEXT NOT NULL,
                reference_window_days INTEGER,
                source_url TEXT NOT NULL,
                match_method TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reference_price_evidence_product
            ON reference_price_evidence (product_id, id);

            CREATE TABLE IF NOT EXISTS sent_notifications (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id),
                alert_type TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                reason TEXT,
                observed_price TEXT,
                currency TEXT,
                destination_label TEXT,
                sent_at TEXT NOT NULL,
                UNIQUE (product_id, fingerprint)
            );

            CREATE INDEX IF NOT EXISTS idx_sent_notifications_product_sent_at
            ON sent_notifications (product_id, sent_at);
            """
        )

    @staticmethod
    def _upsert_product(connection: sqlite3.Connection, offer: ProductOffer) -> int:
        return SQLiteStore._upsert_product_identity(connection, offer.product)

    @staticmethod
    def _record_reference_price_evidence(
        connection: sqlite3.Connection,
        product_id: int,
        evidence: ReferencePriceEvidence,
        *,
        seen_at: datetime,
    ) -> None:
        latest = connection.execute(
            """
            SELECT id, source, scope, reference_kind, reference_price, currency,
                   reference_window_days, source_url, match_method
            FROM reference_price_evidence
            WHERE product_id = ?
              AND source = ?
              AND scope = ?
              AND reference_kind = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (product_id, evidence.source, evidence.scope.value, evidence.kind.value),
        ).fetchone()
        reference_values = (
            evidence.source,
            evidence.scope.value,
            evidence.kind.value,
            format(evidence.price, "f"),
            evidence.currency,
            evidence.reference_window_days,
            evidence.source_url,
            evidence.match_method,
        )
        if (
            latest is not None
            and latest[4] == reference_values[3]
            and latest[5] == reference_values[4]
        ):
            connection.execute(
                "UPDATE reference_price_evidence SET last_seen_at = ? WHERE id = ?",
                (seen_at.isoformat(), latest[0]),
            )
            return
        connection.execute(
            """
            INSERT INTO reference_price_evidence (
                product_id, source, scope, reference_kind, reference_price, currency,
                reference_window_days, source_url, match_method, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, *reference_values, seen_at.isoformat(), seen_at.isoformat()),
        )

    @staticmethod
    def _upsert_product_identity(connection: sqlite3.Connection, product: ProductIdentity) -> int:
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
            availability=Availability(row[3]),
            observed_at=observed_at,
        )
    except (InvalidOperation, ValueError) as error:
        raise PersistenceError("Stored price observation has invalid data") from error


def _reference_evidence_from_row(
    row: tuple[str, str, str, str, str, int | None, str, str, str, str],
) -> ReferencePriceEvidence:
    try:
        return ReferencePriceEvidence(
            source=row[0],
            scope=ReferencePriceScope(row[1]),
            kind=ReferencePriceKind(row[2]),
            price=Decimal(row[3]),
            currency=row[4],
            reference_window_days=row[5],
            source_url=row[6],
            match_method=row[7],
            first_seen_at=_as_utc(datetime.fromisoformat(row[8])),
            last_seen_at=_as_utc(datetime.fromisoformat(row[9])),
        )
    except (InvalidOperation, ValueError) as error:
        raise PersistenceError("Stored reference evidence has invalid data") from error


def _lowest_available(observations: Iterable[PriceObservation]) -> PriceObservation | None:
    available = [
        observation
        for observation in observations
        if observation.availability is Availability.AVAILABLE
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
