"""Command-line interface for the DealWatch PL MVP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

import httpx

from dealwatch.adapters.xkom import DEFAULT_USER_AGENT, XkomCollectionError, XkomGpuCollector
from dealwatch.discord import DiscordNotificationError, send_test_notification
from dealwatch.models import ProductOffer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dealwatch", description="DealWatch PL MVP")
    retailer_commands = parser.add_subparsers(dest="retailer", required=True)
    xkom = retailer_commands.add_parser("xkom", help="Commands for x-kom")
    xkom_commands = xkom.add_subparsers(dest="command", required=True)
    xkom_commands.add_parser("collect-gpus", help="Print normalized x-kom GPU offers as JSON")
    notify = xkom_commands.add_parser("notify-test", help="Send one collected GPU to Discord")
    notify.add_argument("product_id", help="x-kom product ID to send")
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
    environment = environ if environ is not None else os.environ

    try:
        with httpx.Client(
            headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=20.0, follow_redirects=True
        ) as xkom_client:
            offers = XkomGpuCollector(xkom_client).collect_gpus()
        if args.command == "collect-gpus":
            json.dump([offer.to_dict() for offer in offers], output, ensure_ascii=False, indent=2)
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
    except (XkomCollectionError, DiscordNotificationError) as error:
        print(f"Error: {error}", file=errors)
        return 1


def _find_offer(offers: list[ProductOffer], product_id: str) -> ProductOffer:
    for offer in offers:
        if offer.product.retailer_product_id == product_id:
            return offer
    raise XkomCollectionError(f"x-kom product {product_id} was not found in the GPU category")
