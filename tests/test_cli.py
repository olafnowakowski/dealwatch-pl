from __future__ import annotations

import io
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dealwatch import cli
from dealwatch.models import Availability, NotificationEvent, ProductIdentity, ProductOffer
from dealwatch.storage import SQLiteStore


def test_collect_gpus_emits_normalized_json_and_persists_observation(
    monkeypatch, tmp_path: Path
) -> None:
    offer = ProductOffer(
        product=ProductIdentity(
            retailer="x-kom",
            retailer_product_id="1001",
            category="gpu",
            name="Acme GPU",
            brand=None,
            manufacturer_sku=None,
            product_url="https://www.x-kom.pl/p/1001.html",
            image_url=None,
        ),
        price=Decimal("1999"),
        currency="PLN",
        availability=Availability.AVAILABLE,
        previous_price=None,
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(cli.XkomGpuCollector, "collect_gpus", lambda self: [offer])
    stdout = io.StringIO()

    database_path = tmp_path / "dealwatch.sqlite3"
    exit_code = cli.main(
        ["xkom", "collect-gpus"],
        stdout=stdout,
        environ={"DEALWATCH_DATABASE_PATH": str(database_path)},
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue())[0]["price"] == "1999"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 1


def test_quiet_collection_prints_a_compact_completion_line(monkeypatch, tmp_path: Path) -> None:
    offer = ProductOffer(
        product=ProductIdentity(
            retailer="x-kom",
            retailer_product_id="1001",
            category="gpu",
            name="Acme GPU",
            brand=None,
            manufacturer_sku=None,
            product_url="https://www.x-kom.pl/p/1001.html",
            image_url=None,
        ),
        price=Decimal("1999"),
        currency="PLN",
        availability=Availability.AVAILABLE,
        previous_price=None,
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(cli.XkomGpuCollector, "collect_gpus", lambda self: [offer])
    stdout = io.StringIO()

    exit_code = cli.main(
        ["xkom", "collect-gpus", "--quiet"],
        stdout=stdout,
        environ={"DEALWATCH_DATABASE_PATH": str(tmp_path / "dealwatch.sqlite3")},
    )

    assert exit_code == 0
    assert stdout.getvalue() == "Stored 1 x-kom GPU offers.\n"


def test_price_history_reads_existing_database_without_collecting(
    monkeypatch, tmp_path: Path
) -> None:
    offer = ProductOffer(
        product=ProductIdentity(
            retailer="x-kom",
            retailer_product_id="1001",
            category="gpu",
            name="Acme GPU",
            brand=None,
            manufacturer_sku=None,
            product_url="https://www.x-kom.pl/p/1001.html",
            image_url=None,
        ),
        price=Decimal("1999"),
        currency="PLN",
        availability=Availability.AVAILABLE,
        previous_price=None,
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
    )
    database_path = tmp_path / "dealwatch.sqlite3"
    SQLiteStore(database_path).record_collection([offer])
    monkeypatch.setattr(
        cli.XkomGpuCollector,
        "collect_gpus",
        lambda self: (_ for _ in ()).throw(AssertionError("history must not collect")),
    )
    stdout = io.StringIO()

    exit_code = cli.main(
        ["xkom", "price-history", "1001", "--days", "30"],
        stdout=stdout,
        environ={"DEALWATCH_DATABASE_PATH": str(database_path)},
    )

    assert exit_code == 0
    history = json.loads(stdout.getvalue())
    assert history["summary"]["observation_count"] == 1
    assert history["summary"]["all_time_low"]["current_price"] == "1999"
    assert history["analysis"]["windows"]["7_day"]["status"] == "insufficient_history"
    assert history["analysis"]["windows"]["7_day"]["average"] is None


def test_evaluate_gpus_prints_candidates_without_sending_or_recording_notifications(
    monkeypatch, tmp_path: Path
) -> None:
    observed_at = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    offer = ProductOffer(
        product=ProductIdentity(
            retailer="x-kom",
            retailer_product_id="1001",
            category="gpu",
            name="Acme GPU",
            brand=None,
            manufacturer_sku=None,
            product_url="https://www.x-kom.pl/p/1001.html",
            image_url=None,
        ),
        price=Decimal("1800"),
        currency="PLN",
        availability=Availability.AVAILABLE,
        previous_price=Decimal("2400"),
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=observed_at,
    )
    database_path = tmp_path / "dealwatch.sqlite3"
    store = SQLiteStore(database_path)
    store.record_collection(
        [
            replace(
                offer,
                price=Decimal("2000"),
                previous_price=None,
                observed_at=observed_at - timedelta(days=8) + timedelta(hours=hour),
            )
            for hour in range(8 * 24)
        ]
    )
    store.record_successful_notification(
        NotificationEvent(
            product=offer.product,
            alert_type="deal_candidate",
            fingerprint="m7:v1:PLN:1800.00",
            sent_at=observed_at,
        )
    )
    monkeypatch.setattr(cli.XkomGpuCollector, "collect_gpus", lambda self: [offer])
    stdout = io.StringIO()

    exit_code = cli.main(
        ["xkom", "evaluate-gpus"],
        stdout=stdout,
        environ={"DEALWATCH_DATABASE_PATH": str(database_path)},
    )

    assert exit_code == 0
    result = json.loads(stdout.getvalue())
    assert result["evaluated_count"] == 1
    assert result["history_baseline_counts"] == {"sufficient_7d": 1}
    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["history_baseline"] == "sufficient_7d"
    assert candidate["history"]["windows"]["7_day"]["status"] == "sufficient"
    assert candidate["already_notified"]
    assert not candidate["notification_eligible"]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sent_notifications").fetchone()[0] == 1


def test_monitor_gpus_dry_run_persists_observation_but_never_records_notifications(
    monkeypatch, tmp_path: Path
) -> None:
    observed_at = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    offer = ProductOffer(
        product=ProductIdentity(
            retailer="x-kom",
            retailer_product_id="1001",
            category="gpu",
            name="Acme GPU",
            brand=None,
            manufacturer_sku=None,
            product_url="https://www.x-kom.pl/p/1001.html",
            image_url=None,
        ),
        price=Decimal("1800"),
        currency="PLN",
        availability=Availability.AVAILABLE,
        previous_price=Decimal("2000"),
        reported_minimum_price=None,
        promotion_labels=(),
        observed_at=observed_at,
    )
    database_path = tmp_path / "dealwatch.sqlite3"
    store = SQLiteStore(database_path)
    store.record_collection(
        [
            replace(
                offer,
                price=Decimal("2000"),
                previous_price=None,
                observed_at=observed_at - timedelta(days=8) + timedelta(hours=hour),
            )
            for hour in range(8 * 24)
        ]
    )
    monkeypatch.setattr(cli.XkomGpuCollector, "collect_gpus", lambda self: [offer])
    stdout = io.StringIO()

    exit_code = cli.main(
        ["xkom", "monitor-gpus", "--quiet"],
        stdout=stdout,
        environ={"DEALWATCH_DATABASE_PATH": str(database_path)},
    )

    assert exit_code == 0
    result = json.loads(stdout.getvalue())
    assert result["mode"] == "dry_run"
    assert result["candidate_count"] == 1
    assert result["delivered_count"] == 0
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sent_notifications").fetchone()[0] == 0


def test_monitor_gpus_send_requires_webhook_before_collecting(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli.XkomGpuCollector,
        "collect_gpus",
        lambda self: (_ for _ in ()).throw(AssertionError("must not collect without webhook")),
    )
    stderr = io.StringIO()

    exit_code = cli.main(
        ["xkom", "monitor-gpus", "--send"],
        stderr=stderr,
        environ={"DEALWATCH_DATABASE_PATH": str(tmp_path / "dealwatch.sqlite3")},
    )

    assert exit_code == 2
    assert "DISCORD_WEBHOOK_URL" in stderr.getvalue()
