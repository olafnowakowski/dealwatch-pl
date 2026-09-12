from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from decimal import Decimal

from dealwatch import cli
from dealwatch.models import Availability, ProductIdentity, ProductOffer


def test_collect_gpus_emits_normalized_json(monkeypatch) -> None:
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

    exit_code = cli.main(["xkom", "collect-gpus"], stdout=stdout)

    assert exit_code == 0
    assert json.loads(stdout.getvalue())[0]["price"] == "1999"
