"""Command-line interface for the DealWatch PL MVP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

import httpx

from dealwatch.adapters.xkom import DEFAULT_USER_AGENT, XkomCollectionError, XkomGpuCollector
from dealwatch.config import load_dotenv
from dealwatch.deals import evaluate_deal
from dealwatch.discord import DiscordNotificationError, send_test_notification
from dealwatch.models import ProductOffer
from dealwatch.storage import DEFAULT_DATABASE_PATH, PersistenceError, SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dealwatch", description="DealWatch PL MVP")
    retailer_commands = parser.add_subparsers(dest="retailer", required=True)
    xkom = retailer_commands.add_parser("xkom", help="Commands for x-kom")
    xkom_commands = xkom.add_subparsers(dest="command", required=True)
    collect = xkom_commands.add_parser(
        "collect-gpus", help="Collect and persist x-kom GPU offers"
    )
    collect.add_argument(
        "--quiet",
        action="store_true",
        help="Print one completion line instead of the full normalized JSON payload",
    )
    notify = xkom_commands.add_parser("notify-test", help="Send one collected GPU to Discord")
    notify.add_argument("product_id", help="x-kom product ID to send")
    xkom_commands.add_parser(
        "evaluate-gpus",
        help="Collect, persist, and print explained deal candidates without notifying",
    )
    history = xkom_commands.add_parser(
        "price-history", help="Print stored price history for one GPU"
    )
    history.add_argument("product_id", help="x-kom product ID to inspect")
    history.add_argument(
        "--days",
        type=_positive_integer,
        default=30,
        help="Recent-minimum window in days (default: 30)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run a CLI command and return a process-style exit code."""

    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    args = build_parser().parse_args(argv)
    if environ is None:
        try:
            load_dotenv()
        except ValueError as error:
            print(f"Configuration error: {error}", file=errors)
            return 2
        environment: Mapping[str, str] = os.environ
    else:
        environment = environ

    try:
        store = SQLiteStore(_database_path(environment))
        if args.command == "price-history":
            history = store.get_price_history(
                "x-kom", args.product_id, recent_window_days=args.days
            )
            if history is None:
                print(
                    f"Error: x-kom product {args.product_id} has no stored price history.",
                    file=errors,
                )
                return 1
            json.dump(history.to_dict(), output, ensure_ascii=False, indent=2)
            output.write("\n")
            return 0

        with httpx.Client(
            headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=20.0, follow_redirects=True
        ) as xkom_client:
            offers = XkomGpuCollector(xkom_client).collect_gpus()
        store.record_collection(offers)
        if args.command == "collect-gpus":
            if args.quiet:
                print(f"Stored {len(offers)} x-kom GPU offers.", file=output)
                return 0
            json.dump([offer.to_dict() for offer in offers], output, ensure_ascii=False, indent=2)
            output.write("\n")
            return 0

        if args.command == "evaluate-gpus":
            candidates, baseline_counts = _evaluate_offers(store, offers)
            json.dump(
                {
                    "evaluated_count": len(offers),
                    "history_baseline_counts": baseline_counts,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                },
                output,
                ensure_ascii=False,
                indent=2,
            )
            output.write("\n")
            return 0

        webhook_url = environment.get("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            print("DISCORD_WEBHOOK_URL must be set for notify-test.", file=errors)
            return 2
        offer = _find_offer(offers, args.product_id)
        with httpx.Client(timeout=20.0) as discord_client:
            send_test_notification(discord_client, webhook_url, offer)
        print(f"Sent test notification for x-kom product {args.product_id}.", file=output)
        return 0
    except (XkomCollectionError, DiscordNotificationError, PersistenceError) as error:
        print(f"Error: {error}", file=errors)
        return 1


def _find_offer(offers: list[ProductOffer], product_id: str) -> ProductOffer:
    for offer in offers:
        if offer.product.retailer_product_id == product_id:
            return offer
    raise XkomCollectionError(f"x-kom product {product_id} was not found in the GPU category")


def _evaluate_offers(
    store: SQLiteStore,
    offers: list[ProductOffer],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    candidates: list[dict[str, object]] = []
    baseline_counts: dict[str, int] = {}
    for offer in offers:
        history = store.get_price_history(
            offer.product.retailer,
            offer.product.retailer_product_id,
            as_of=offer.observed_at,
        )
        if history is None:
            raise PersistenceError(
                f"Persisted x-kom product {offer.product.retailer_product_id} could not be read"
            )
        evaluation = evaluate_deal(offer, history)
        baseline = evaluation.history_baseline.value
        baseline_counts[baseline] = baseline_counts.get(baseline, 0) + 1
        candidate = evaluation.candidate
        if candidate is None:
            continue
        already_notified = store.has_successful_notification_for(
            candidate.product,
            candidate.fingerprint,
        )
        payload = candidate.to_dict()
        payload["history"] = evaluation.history_analysis.to_dict()
        payload["already_notified"] = already_notified
        payload["notification_eligible"] = not already_notified
        candidates.append(payload)
    return candidates, baseline_counts


def _database_path(environment: Mapping[str, str]) -> Path:
    configured_path = environment.get("DEALWATCH_DATABASE_PATH")
    return Path(configured_path) if configured_path else DEFAULT_DATABASE_PATH


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed
