from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from dealwatch.adapters.xkom import XkomCollectionError, XkomGpuCollector, extract_initial_state
from dealwatch.models import Availability

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_1 = (FIXTURES / "xkom_gpu_page_1.html").read_text(encoding="utf-8")
PAGE_2 = (FIXTURES / "xkom_gpu_page_2.html").read_text(encoding="utf-8")


def test_collects_paginated_products_and_normalizes_offers() -> None:
    requests: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        page = request.url.params.get("page")
        return httpx.Response(200, text=PAGE_2 if page == "2" else PAGE_1, request=request)

    observed_at = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        offers = XkomGpuCollector(
            client,
            category_url="https://www.x-kom.pl/g-5/c/345-karty-graficzne.html?per_page=60",
            sleep=sleeps.append,
            clock=lambda: observed_at,
        ).collect_gpus()

    assert [offer.product.retailer_product_id for offer in offers] == [
        "1001",
        "1002",
        "1003",
        "1004",
        "1005",
    ]
    assert len(requests) == 2
    assert sleeps == [1.0]

    regular, discounted, unavailable, minimal, unknown = offers
    assert regular.price == 1999
    assert regular.product.product_url == "https://www.x-kom.pl/p/1001-acme-gpu.html"
    assert regular.observed_at == observed_at
    assert discounted.previous_price == Decimal("2999.99")
    assert discounted.reported_minimum_price == Decimal("2599.99")
    assert discounted.promotion_labels == ("Autumn sale", "Bundle")
    assert unavailable.availability is Availability.OUT_OF_STOCK
    assert minimal.product.brand is None
    assert minimal.product.image_url is None
    assert unknown.availability is Availability.UNKNOWN


def test_retries_transient_server_failures() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, text=PAGE_2, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        offers = XkomGpuCollector(
            client,
            retries=1,
            retry_backoff_seconds=0.25,
            sleep=sleeps.append,
        ).collect_gpus()

    assert attempts == 2
    assert sleeps == [0.25]
    assert len(offers) == 2


def test_rejects_missing_initial_state() -> None:
    with pytest.raises(XkomCollectionError, match="initial-state payload was not found"):
        extract_initial_state("<html></html>")


def test_rejects_listing_product_missing_from_payload() -> None:
    state = extract_initial_state(PAGE_1)
    del state["products"]["1001"]

    with pytest.raises(XkomCollectionError, match="1001 is missing"):
        from dealwatch.adapters.xkom import map_listing_products

        map_listing_products(state, observed_at=datetime.now(UTC))
