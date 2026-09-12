"""HTTP collector for the x-kom graphics-card category."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from dealwatch.models import (
    Availability,
    ProductIdentity,
    ProductOffer,
    ReferencePriceEvidence,
    ReferencePriceKind,
    ReferencePriceScope,
)

BASE_URL = "https://www.x-kom.pl"
GPU_CATEGORY_URL = f"{BASE_URL}/g-5/c/345-karty-graficzne.html?per_page=60"
DEFAULT_USER_AGENT = "DealWatchPL/0.1 (+https://github.com/olafn/dealwatch-pl)"
INITIAL_STATE_MARKER = "window.__INITIAL_STATE__['app'] = "


class XkomCollectionError(RuntimeError):
    """Raised when x-kom data cannot be fetched or normalized safely."""


class XkomGpuCollector:
    """Collect server-rendered x-kom GPU listings through ordinary HTTP."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        category_url: str = GPU_CATEGORY_URL,
        request_delay_seconds: float = 1.0,
        max_pages: int = 10,
        retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._category_url = category_url
        self._request_delay_seconds = request_delay_seconds
        self._max_pages = max_pages
        self._retries = retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep
        self._clock = clock

    def collect_gpus(self) -> list[ProductOffer]:
        """Return every unique GPU listing reachable from the category page."""

        current_url: str | None = self._category_url
        visited_urls: set[str] = set()
        offers: list[ProductOffer] = []
        seen_product_ids: set[str] = set()
        observed_at = _as_utc(self._clock())

        for _page_number in range(1, self._max_pages + 1):
            if current_url is None:
                return offers
            if current_url in visited_urls:
                raise XkomCollectionError(f"Pagination loop detected at {current_url}")
            visited_urls.add(current_url)

            response = self._get_page(current_url)
            state = extract_initial_state(response.text)
            for offer in map_listing_products(state, observed_at=observed_at):
                if offer.product.retailer_product_id not in seen_product_ids:
                    offers.append(offer)
                    seen_product_ids.add(offer.product.retailer_product_id)

            current_url = extract_next_page_url(response.text, response.url)
            if current_url is not None:
                self._sleep(self._request_delay_seconds)

        if current_url is not None:
            raise XkomCollectionError(
                f"Pagination exceeded the configured limit of {self._max_pages} pages"
            )
        return offers

    def _get_page(self, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                response = self._client.get(url)
            except httpx.RequestError as error:
                last_error = error
                if attempt == self._retries:
                    break
                self._sleep(self._retry_backoff_seconds * (2**attempt))
                continue

            if response.status_code < 500:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    raise XkomCollectionError(
                        f"x-kom returned HTTP {response.status_code} for {url}"
                    ) from error
                return response

            last_error = httpx.HTTPStatusError(
                f"x-kom returned HTTP {response.status_code}",
                request=response.request,
                response=response,
            )
            if attempt == self._retries:
                break
            self._sleep(self._retry_backoff_seconds * (2**attempt))

        raise XkomCollectionError(f"Could not fetch x-kom page {url}: {last_error}") from last_error


def extract_initial_state(html: str) -> dict[str, Any]:
    """Parse x-kom's server-rendered application JSON without executing JavaScript."""

    marker_index = html.find(INITIAL_STATE_MARKER)
    if marker_index == -1:
        raise XkomCollectionError("x-kom initial-state payload was not found")

    object_start = html.find("{", marker_index + len(INITIAL_STATE_MARKER))
    if object_start == -1:
        raise XkomCollectionError("x-kom initial-state payload does not start with an object")

    object_end = _find_json_object_end(html, object_start)
    try:
        state = json.loads(html[object_start:object_end])
    except json.JSONDecodeError as error:
        raise XkomCollectionError("x-kom initial-state payload is not valid JSON") from error
    if not isinstance(state, dict):
        raise XkomCollectionError("x-kom initial-state payload is not an object")
    return state


def map_listing_products(state: dict[str, Any], *, observed_at: datetime) -> list[ProductOffer]:
    """Map the ordered listing references in x-kom state to normalized offers."""

    try:
        listing = state["productsLists"]["listingContainer"]
        products = state["products"]
    except (KeyError, TypeError) as error:
        raise XkomCollectionError("x-kom listing payload has an unexpected shape") from error
    if not isinstance(listing, list) or not isinstance(products, dict):
        raise XkomCollectionError("x-kom listing payload has an unexpected shape")

    offers: list[ProductOffer] = []
    for listing_item in listing:
        if not isinstance(listing_item, dict) or "id" not in listing_item:
            raise XkomCollectionError("x-kom listing item is missing an ID")
        product_id = str(listing_item["id"])
        raw_product = products.get(product_id)
        if not isinstance(raw_product, dict):
            raise XkomCollectionError(f"x-kom product {product_id} is missing from its payload")
        offers.append(_map_product(product_id, raw_product, observed_at=observed_at))
    return offers


def extract_next_page_url(html: str, current_url: httpx.URL) -> str | None:
    """Return the document's pagination next URL, if present."""

    parser = _NextLinkParser()
    parser.feed(html)
    parser.close()
    return urljoin(str(current_url), parser.next_href) if parser.next_href else None


def _map_product(product_id: str, raw: dict[str, Any], *, observed_at: datetime) -> ProductOffer:
    name = _required_string(raw, "fullName", product_id)
    product_link = _required_string(raw, "productLink", product_id)
    price_info = raw.get("priceInfo") if isinstance(raw.get("priceInfo"), dict) else raw
    price = _decimal(_first_present(price_info, raw, "price"), "price", product_id)
    producer = raw.get("producer") if isinstance(raw.get("producer"), dict) else {}
    photo = raw.get("photo") if isinstance(raw.get("photo"), dict) else {}

    identity = ProductIdentity(
        retailer="x-kom",
        retailer_product_id=product_id,
        category="gpu",
        name=name,
        brand=_optional_string(producer.get("name")),
        manufacturer_sku=_optional_string(raw.get("producerCode")),
        product_url=urljoin(BASE_URL, product_link),
        image_url=_optional_string(photo.get("url")),
    )
    reported_minimum_price = _optional_decimal(price_info.get("minPrice"), "minPrice", product_id)
    if reported_minimum_price is not None and reported_minimum_price <= 0:
        reported_minimum_price = None
    reference_price_evidence = (
        (
            ReferencePriceEvidence(
                source="x-kom",
                scope=ReferencePriceScope.RETAILER,
                kind=ReferencePriceKind.XCOM_REPORTED_LOWEST_PRICE_LAST_30_DAYS,
                price=reported_minimum_price,
                currency="PLN",
                reference_window_days=30,
                source_url=identity.product_url,
                match_method="direct_retailer_product_id",
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            ),
        )
        if reported_minimum_price is not None
        else ()
    )
    labels = tuple(
        dict.fromkeys(
            label
            for badge in raw.get("badges", [])
            if isinstance(badge, dict)
            if (label := _optional_string(badge.get("promoLabel") or badge.get("name")))
        )
    )
    return ProductOffer(
        product=identity,
        price=price,
        currency="PLN",
        availability=_availability(raw.get("availabilityStatus")),
        previous_price=_optional_decimal(price_info.get("oldPrice"), "oldPrice", product_id),
        reported_minimum_price=reported_minimum_price,
        promotion_labels=labels,
        observed_at=observed_at,
        reference_price_evidence=reference_price_evidence,
    )


def _first_present(primary: dict[str, Any], fallback: dict[str, Any], key: str) -> Any:
    return primary[key] if key in primary else fallback.get(key)


def _required_string(raw: dict[str, Any], key: str, product_id: str) -> str:
    value = _optional_string(raw.get(key))
    if value is None:
        raise XkomCollectionError(f"x-kom product {product_id} is missing {key}")
    return value


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _decimal(value: Any, field: str, product_id: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise XkomCollectionError(f"x-kom product {product_id} has an invalid {field}") from error


def _optional_decimal(value: Any, field: str, product_id: str) -> Decimal | None:
    return _decimal(value, field, product_id) if value is not None else None


def _availability(value: Any) -> Availability:
    normalized = str(value).casefold().replace(" ", "")
    if normalized == "available":
        return Availability.AVAILABLE
    if normalized in {"unavailable", "outofstock", "notavailable"}:
        return Availability.OUT_OF_STOCK
    return Availability.UNKNOWN


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _find_json_object_end(value: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(value)):
        character = value[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    raise XkomCollectionError("x-kom initial-state payload is incomplete")


class _NextLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.next_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link" or self.next_href is not None:
            return
        attributes = dict(attrs)
        rel = attributes.get("rel", "")
        if rel and "next" in rel.split() and attributes.get("href"):
            self.next_href = attributes["href"]
