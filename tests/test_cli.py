from __future__ import annotations

import io
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from dealwatch import cli
from dealwatch.models import Availability, ProductIdentity, ProductOffer


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
