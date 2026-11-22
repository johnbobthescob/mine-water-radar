"""Argument parser and explicit pre-implementation command stubs."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from .config import (
    DEFAULT_DB,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RAW_DIR,
    DEFAULT_REPORT_DAYS,
    DEFAULT_TENEMENT_SITE_LIMIT,
    perth_today,
)


def _date_arg(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a date in YYYY-MM-DD format") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("expected a date in YYYY-MM-DD format")
    return parsed


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a nonnegative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative integer")
    return parsed


def _positive_int(value: str) -> int:
    parsed = _nonnegative_int(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m radar",
        description="Local WA mine-water evidence and opportunity research pipeline.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="fetch and ingest a source run")
    score = commands.add_parser("score", help="score the latest usable source run")
    report = commands.add_parser("report", help="write local reports from saved scores")
    all_cmd = commands.add_parser("all", help="fetch, score and write local reports")

    for subparser in (fetch, score, report, all_cmd):
        subparser.add_argument("--db", type=Path, default=DEFAULT_DB, metavar="PATH")
        subparser.add_argument("--as-of", type=_date_arg, default=perth_today(), metavar="YYYY-MM-DD")

    for subparser in (fetch, all_cmd):
        subparser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, metavar="PATH")
        subparser.add_argument("--fixture-dir", type=Path, metavar="PATH")
        subparser.add_argument(
            "--tenement-site-limit",
            type=_nonnegative_int,
            default=DEFAULT_TENEMENT_SITE_LIMIT,
            metavar="N",
            help="maximum sampled site lookups; zero disables tenure enrichment",
        )

    for subparser in (score, fetch, all_cmd):
        subparser.add_argument("--reviewed-evidence", type=Path, metavar="PATH")

    for subparser in (report, all_cmd):
        subparser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR, metavar="PATH")
        subparser.add_argument("--days", type=_positive_int, default=DEFAULT_REPORT_DAYS, metavar="N")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    print(
        f"radar {args.command}: not implemented in M1; no database or network work was performed.",
        file=sys.stderr,
    )
    return 1
