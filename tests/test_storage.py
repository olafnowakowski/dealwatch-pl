from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dealwatch.models import (
    Availability,
    ProductIdentity,
    ProductOffer,
    ReferencePriceEvidence,
    ReferencePriceKind,
    ReferencePriceScope,
)
from dealwatch.storage import PersistenceError, SQLiteStore


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


def _xkom_reference(price: str, seen_at: datetime) -> ReferencePriceEvidence:
    return ReferencePriceEvidence(
        source="x-kom",
        scope=ReferencePriceScope.RETAILER,
        kind=ReferencePriceKind.XCOM_REPORTED_LOWEST_PRICE_LAST_30_DAYS,
        price=Decimal(price),
        currency="PLN",
        reference_window_days=30,
        source_url="https://www.x-kom.pl/p/1001-acme-gpu.html",
        match_method="direct_retailer_product_id",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
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


def test_price_history_keeps_the_earliest_observation_when_lows_are_equal(tmp_path: Path) -> None:
    database_path = tmp_path / "dealwatch.sqlite3"
    as_of = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    store = SQLiteStore(database_path)
    store.record_collection(
        [
            _offer(price="1500", observed_at=as_of - timedelta(hours=2)),
            _offer(price="1500", observed_at=as_of - timedelta(hours=1)),
        ]
    )

    history = store.get_price_history("x-kom", "1001", as_of=as_of)

    assert history is not None
    assert history.all_time_low is not None
    assert history.all_time_low.observed_at == as_of - timedelta(hours=2)


def test_failed_collection_rolls_back_without_changing_existing_history(
    monkeypatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "dealwatch.sqlite3"
    store = SQLiteStore(database_path)
    observed_at = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    store.record_collection([_offer(price="1999", observed_at=observed_at)])

    def fail_upsert(connection: sqlite3.Connection, offer: ProductOffer) -> int:
        raise sqlite3.OperationalError("simulated persistence failure")

    monkeypatch.setattr(store, "_upsert_product", fail_upsert)

    import pytest

    with pytest.raises(PersistenceError, match="Could not persist collection"):
        store.record_collection(
            [_offer(price="1899", observed_at=observed_at + timedelta(hours=1))]
        )

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 1


def test_reference_evidence_uses_contiguous_episodes_without_native_history_contamination(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "dealwatch.sqlite3"
    store = SQLiteStore(database_path)
    first_seen = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    for hours, reference_price in ((0, "600"), (1, "600"), (2, "500"), (3, "600")):
        observed_at = first_seen + timedelta(hours=hours)
        store.record_collection(
            [
                replace(
                    _offer(price="550", observed_at=observed_at),
                    reference_price_evidence=(_xkom_reference(reference_price, observed_at),),
                )
            ]
        )

    evidence = store.get_reference_price_evidence("x-kom", "1001")

    assert [(item.price, item.first_seen_at, item.last_seen_at) for item in evidence] == [
        (Decimal("600"), first_seen, first_seen + timedelta(hours=1)),
        (Decimal("500"), first_seen + timedelta(hours=2), first_seen + timedelta(hours=2)),
        (Decimal("600"), first_seen + timedelta(hours=3), first_seen + timedelta(hours=3)),
    ]
    with sqlite3.connect(database_path) as connection:
        reference_count = connection.execute(
            "SELECT COUNT(*) FROM reference_price_evidence"
        ).fetchone()[0]
        assert reference_count == 3
        assert connection.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 4
