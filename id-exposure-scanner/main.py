#!/usr/bin/env python3
"""
ID Exposure Scanner
═══════════════════
CLI tool for scanning the public exposure of a test identifier
across search engines and public platforms.

Usage:
    python main.py <identifier> [options]

This tool is designed to run exclusively in an isolated testing
environment (Docker / sandbox) as part of an authorized exposure
assessment program.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from config import Config
from modules.normalizer import normalize
from modules.search_engines import (
    search_google,
    search_bing,
    search_yahoo,
    search_duckduckgo_html,
    SearchResult,
    normalize_url,
    score_result,
)
import modules.search_engines as se_module
from modules.platforms import scan_all_platforms
from modules.reporter import generate_reports, print_summary
from modules.email_search import search_emails_google_dork, search_emails_from_platform_results, check_email_breaches
from modules.network_check import network_enrichment


# ═══════════════════════════════════════════════════════════════
#  Logging setup
# ═══════════════════════════════════════════════════════════════

def _setup_logging(log_level: str, output_dir: Path) -> None:
    """Configure loguru sinks: stderr + rotating file."""
    logger.remove()

    logger.add(
        sys.stderr,
        level=log_level.upper(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        output_dir / "scanner_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="1 day",
        retention="30 days",
        encoding="utf-8",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} - {message}"
        ),
    )


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="id-exposure-scanner",
        description="Scan public exposure of a test identifier across the internet.",
        epilog="\u26a0  For authorized security testing only.",
    )
    parser.add_argument(
        "identifier",
        help="The numeric identifier / code to scan (e.g. phone number, ID number).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=None,
        help="Override output directory (default: ./output).",
    )
    parser.add_argument(
        "-m", "--max-results",
        type=int,
        default=None,
        help="Max results per source (default: from .env or 20).",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log verbosity (default: from .env or INFO).",
    )
    parser.add_argument(
        "--skip-search-engines",
        action="store_true",
        help="Skip Google, Bing, Yahoo, and DuckDuckGo searches.",
    )
    parser.add_argument(
        "--skip-platforms",
        action="store_true",
        help="Skip platform checks (GitHub, Reddit, social media, etc.).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output (show raw HTTP responses and full debug info).",
    )
    parser.add_argument(
        "--search-emails",
        action="store_true",
        help="Search for associated email addresses.",
    )
    parser.add_argument(
        "--network-scan",
        action="store_true",
        help="Perform passive network checks (DNS/WHOIS) on extracted domains/IPs.",
    )
    parser.add_argument(
        "--hibp-api-key",
        default=None,
        help="HaveIBeenPwned API key for email breach checks.",
    )
    parser.add_argument(
        "--min-relevance",
        type=float,
        default=0.0,
        metavar="SCORE",
        help=(
            "Filter out results with relevance score below this threshold (0.0–1.0). "
            "0.0 = keep all (default). Try 0.15 to remove noise, 0.35 for high-confidence only."
        ),
    )
    return parser


# ═══════════════════════════════════════════════════════════════
#  Deduplication helpers
# ═══════════════════════════════════════════════════════════════

def _dedup_results(results: list[SearchResult]) -> list[SearchResult]:
    """
    Deduplicate results using normalised URLs.
    Normalisation strips tracking params, lowercases scheme/host,
    and removes trailing slashes — so the same page isn't counted twice
    just because it was found via different query variants.
    """
    seen: set[str] = set()
    unique: list[SearchResult] = []
    for r in results:
        if not r.link:
            continue
        key = normalize_url(r.link)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ═══════════════════════════════════════════════════════════════
#  Main logic
# ═══════════════════════════════════════════════════════════════

def run(args: argparse.Namespace) -> None:
    output_dir = args.output_dir or Config.OUTPUT_DIR
    log_level = args.log_level or Config.LOG_LEVEL
    max_results = args.max_results or Config.MAX_RESULTS_PER_SOURCE
    min_relevance: float = max(0.0, min(1.0, args.min_relevance))

    if args.verbose:
        log_level = "DEBUG"
        se_module.VERBOSE = True

    _setup_logging(log_level, output_dir)
    logger.info("=" * 60)
    logger.info("ID Exposure Scanner v2 — Starting")
    logger.info("=" * 60)
    start = time.monotonic()

    # 1. Normalize identifier
    norm = normalize(args.identifier)
    canonical = norm["canonical"]
    variants = norm["variants"]
    id_type = norm.get("id_type", "generic")
    logger.info("Canonical ID : {}", canonical)
    logger.info("ID type      : {}", id_type)
    logger.info("Variants ({}): {}", len(variants), variants)

    all_results: list[SearchResult] = []

    # 2. Search engines — search all variants
    if not args.skip_search_engines:
        logger.info("\u2550" * 50)
        logger.info("Phase 1: Search Engines")
        logger.info("\u2550" * 50)
        for i, variant in enumerate(variants, 1):
            logger.info("\u2500\u2500 Variant {}/{}: {} \u2500\u2500", i, len(variants), variant)
            all_results.extend(search_google(variant, max_results=max_results))
            all_results.extend(search_bing(variant, max_results=max_results))
            all_results.extend(search_yahoo(variant, max_results=max_results))
            # DuckDuckGo HTML on canonical + quoted variants (not every variant to avoid rate-limit)
            if variant == canonical or variant.startswith('"'):
                all_results.extend(search_duckduckgo_html(variant, max_results=max_results))
    else:
        logger.info("Skipping search engines (--skip-search-engines)")

    # 3. Public platforms — use canonical + key variants
    if not args.skip_platforms:
        logger.info("\u2550" * 50)
        logger.info("Phase 2: Public Platforms")
        logger.info("\u2550" * 50)
        all_results.extend(scan_all_platforms(canonical, max_results=max_results))

        # Also run platform scans for key non-quoted variants
        key_variants = [v for v in variants if not v.startswith('"') and v != canonical]
        for v in key_variants[:3]:
            logger.info("\u2500\u2500 Platform scan for variant: {} \u2500\u2500", v)
            all_results.extend(scan_all_platforms(v, max_results=max_results))
    else:
        logger.info("Skipping platforms (--skip-platforms)")

    # 4. Deduplicate by normalised URL
    unique_results = _dedup_results(all_results)
    logger.info("Dedup: {} raw \u2192 {} unique", len(all_results), len(unique_results))

    # 5. Relevance scoring
    logger.info("\u2550" * 50)
    logger.info("Relevance Scoring")
    logger.info("\u2550" * 50)
    for r in unique_results:
        r.relevance_score = score_result(r, canonical, variants)

    # Optional relevance filter
    if min_relevance > 0.0:
        before = len(unique_results)
        unique_results = [r for r in unique_results if r.relevance_score >= min_relevance]
        logger.info(
            "Relevance filter (>= {:.2f}): {} \u2192 {} results",
            min_relevance, before, len(unique_results),
        )

    # Sort by descending relevance for report readability
    unique_results.sort(key=lambda r: r.relevance_score, reverse=True)

    extended_info: dict = {}

    # 6. Email search (Optional)
    if args.search_emails:
        logger.info("\u2550" * 50)
        logger.info("Phase 3: Email Search")
        logger.info("\u2550" * 50)

        emails_from_dork = search_emails_google_dork(canonical, variants)
        platform_emails = search_emails_from_platform_results(unique_results)

        all_emails = set(platform_emails)
        for e in emails_from_dork:
            all_emails.add(e["email"])

        logger.info("Found {} total unique emails", len(all_emails))

        hibp_results = []
        api_key = args.hibp_api_key or Config.HIBP_API_KEY
        for em in all_emails:
            logger.info("Checking breaches for: {}", em)
            hibp_results.append(check_email_breaches(em, api_key))

        extended_info["emails"] = {
            "dork_results": emails_from_dork,
            "extracted_from_platforms": platform_emails,
            "hibp": hibp_results,
        }

    # 7. Network Checks (Optional)
    if args.network_scan:
        logger.info("\u2550" * 50)
        logger.info("Phase 4: Network Enrichment")
        logger.info("\u2550" * 50)
        net_info = network_enrichment(unique_results, active_ports=False)
        extended_info["network"] = net_info

    # ── Summary ──
    logger.info("\u2550" * 50)
    logger.info("Results Summary")
    logger.info("\u2550" * 50)
    logger.info("Total raw results    : {}", len(all_results))
    logger.info("After dedup          : {}", len(unique_results) + (0 if min_relevance == 0 else 0))
    if min_relevance > 0.0:
        logger.info("After relevance filter: {}", len(unique_results))
    high_conf = sum(1 for r in unique_results if r.relevance_score >= 0.50)
    if high_conf:
        logger.info("High-confidence hits (score \u2265 0.50): {}", high_conf)
    if "emails" in extended_info:
        total_emails = (
            len(extended_info["emails"].get("dork_results", []))
            + len(extended_info["emails"].get("extracted_from_platforms", []))
        )
        logger.info("Emails found         : {}", total_emails)

    # 8. Report
    print_summary(unique_results)
    files = generate_reports(
        identifier=args.identifier,
        normalization=norm,
        results=unique_results,
        extended_info=extended_info,
        output_dir=output_dir,
    )

    elapsed = time.monotonic() - start
    logger.info("\u2500" * 50)
    logger.info("Scan completed in {:.1f}s", elapsed)
    logger.info("JSON \u2192 {}", files["json_path"])
    logger.info("CSV  \u2192 {}", files["csv_path"])
    logger.info("SHA  \u2192 {}", files["manifest_path"])


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Fatal error: {}", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
