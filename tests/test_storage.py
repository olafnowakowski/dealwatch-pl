from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dealwatch.models import Availability, ProductIdentity, ProductOffer
from dealwatch.storage import SQLiteStore


def _offer(
    *,
    price: str,
    observed_at: datetime,
    name: str = "Acme GPU",
    product_url: str = "https://www.x-kom.pl/p/1001-acme-gpu.html",
    old_price: str | None = None,
) -> ProductOffer:
    return ProductOffer(
        product=ProductIdentity(
            retailer="x-kom",
            retailer_product_id="1001",
            category="gpu",
            name=name,
            brand="Acme",
            manufacturer_sku="ACME-1001",
            product_url=product_url,
            image_url=None,
        ),
        price=Decimal(price),
        currency="PLN",
        availability=Availability.AVAILABLE,
        previous_price=Decimal(old_price) if old_price else None,
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=observed_at,
    )


def test_repeated_collection_upserts_product_and_appends_observations(tmp_path: Path) -> None:
    database_path = tmp_path / "dealwatch.sqlite3"
    store = SQLiteStore(database_path)
    first_observed_at = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    second_observed_at = first_observed_at + timedelta(hours=1)

    assert store.record_collection([_offer(price="1999", observed_at=first_observed_at)]) == 1
    assert (
        store.record_collection(
            [
                _offer(
                    price="1899.50",
                    old_price="1999",
                    observed_at=second_observed_at,
                    name="Acme GPU Revised",
                    product_url="https://www.x-kom.pl/p/1001-acme-gpu-revised.html",
                )
            ]
        )
        == 1
    )

    with sqlite3.connect(database_path) as connection:
        products = connection.execute(
            "SELECT retailer, retailer_product_id, name, product_url FROM products"
        ).fetchall()
        observations = connection.execute(
            """
            SELECT current_price, currency, old_price, availability, observed_at
            FROM price_observations
            ORDER BY id
            """
        ).fetchall()

    assert products == [
        (
            "x-kom",
            "1001",
            "Acme GPU Revised",
            "https://www.x-kom.pl/p/1001-acme-gpu-revised.html",
        )
    ]
    assert observations == [
        ("1999", "PLN", None, "available", first_observed_at.isoformat()),
        ("1899.50", "PLN", "1999", "available", second_observed_at.isoformat()),
    ]


def test_collection_records_an_observation_for_each_product(tmp_path: Path) -> None:
    database_path = tmp_path / "dealwatch.sqlite3"
    observed_at = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    first = _offer(price="1999", observed_at=observed_at)
    second = ProductOffer(
        product=ProductIdentity(
            retailer="x-kom",
            retailer_product_id="1002",
            category="gpu",
            name="Second GPU",
            brand=None,
            manufacturer_sku=None,
            product_url="https://www.x-kom.pl/p/1002-second-gpu.html",
            image_url=None,
        ),
        price=Decimal("2999"),
        currency="PLN",
        availability=Availability.OUT_OF_STOCK,
        previous_price=Decimal("3199"),
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=observed_at,
    )

    SQLiteStore(database_path).record_collection([first, second])

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 2


def test_price_history_returns_ordered_observations_and_available_price_lows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "dealwatch.sqlite3"
    store = SQLiteStore(database_path)
    as_of = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    store.record_collection(
        [
            _offer(price="1000", observed_at=as_of - timedelta(days=40)),
            _offer(price="1800", observed_at=as_of - timedelta(days=20)),
            _offer(price="1500", old_price="1800", observed_at=as_of),
        ]
    )

    history = store.get_price_history("x-kom", "1001", recent_window_days=30, as_of=as_of)

    assert history is not None
    assert history.product.name == "Acme GPU"
    assert [observation.current_price for observation in history.observations] == [
        Decimal("1000"),
        Decimal("1800"),
        Decimal("1500"),
    ]
    assert history.current_observation is not None
    assert history.current_observation.current_price == Decimal("1500")
    assert history.previous_observation is not None
    assert history.previous_observation.current_price == Decimal("1800")
    assert history.all_time_low is not None
    assert history.all_time_low.current_price == Decimal("1000")
    assert history.recent_minimum is not None
    assert history.recent_minimum.current_price == Decimal("1500")


def test_price_history_ignores_unavailable_observations_for_low_prices(tmp_path: Path) -> None:
    database_path = tmp_path / "dealwatch.sqlite3"
    as_of = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    available = _offer(price="1500", observed_at=as_of - timedelta(days=1))
    unavailable = ProductOffer(
        product=available.product,
        price=Decimal("1"),
        currency="PLN",
        availability=Availability.OUT_OF_STOCK,
        previous_price=None,
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=as_of,
    )
    store = SQLiteStore(database_path)
    store.record_collection([available, unavailable])

    history = store.get_price_history("x-kom", "1001", as_of=as_of)

    assert history is not None
    assert history.all_time_low is not None
    assert history.all_time_low.current_price == Decimal("1500")
