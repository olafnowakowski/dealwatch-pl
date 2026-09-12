"""Minimal SQLite persistence for product identities and price observations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from dealwatch.models import ProductOffer

DEFAULT_DATABASE_PATH = Path("data/dealwatch.sqlite3")


class PersistenceError(RuntimeError):
    """Raised when a collection cannot be persisted safely."""


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
