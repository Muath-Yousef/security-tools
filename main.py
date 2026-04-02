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

from loguru import logger

from config import Config
from modules.normalizer import normalize
from modules.search_engines import search_google, search_bing, search_yahoo, SearchResult
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
    logger.remove()  # Remove default handler

    # Console
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

    # File (rotated daily, retained 30 days)
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
        epilog="⚠  For authorized security testing only.",
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
        help="Skip Google & Bing searches.",
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
    return parser


# ═══════════════════════════════════════════════════════════════
#  Main logic
# ═══════════════════════════════════════════════════════════════

def run(args: argparse.Namespace) -> None:
    output_dir = args.output_dir or Config.OUTPUT_DIR
    log_level = args.log_level or Config.LOG_LEVEL
    max_results = args.max_results or Config.MAX_RESULTS_PER_SOURCE

    # If --verbose, force DEBUG log level and enable raw HTTP logging
    if args.verbose:
        log_level = "DEBUG"
        se_module.VERBOSE = True

    _setup_logging(log_level, output_dir)
    logger.info("=" * 60)
    logger.info("ID Exposure Scanner — Starting")
    logger.info("=" * 60)
    start = time.monotonic()

    # 1. Normalize identifier
    norm = normalize(args.identifier)
    canonical = norm["canonical"]
    variants = norm["variants"]
    logger.info("Canonical ID : {}", canonical)
    logger.info("Variants ({}): {}", len(variants), variants)

    all_results: list[SearchResult] = []

    # 2. Search engines — search all variants
    if not args.skip_search_engines:
        logger.info("═" * 50)
        logger.info("Phase 1: Search Engines")
        logger.info("═" * 50)
        for i, variant in enumerate(variants, 1):
            logger.info("── Variant {}/{}: {} ──", i, len(variants), variant)
            all_results.extend(search_google(variant, max_results=max_results))
            all_results.extend(search_bing(variant, max_results=max_results))
            all_results.extend(search_yahoo(variant, max_results=max_results))
    else:
        logger.info("Skipping search engines (--skip-search-engines)")

    # 3. Public platforms — use canonical + key variants
    if not args.skip_platforms:
        logger.info("═" * 50)
        logger.info("Phase 2: Public Platforms")
        logger.info("═" * 50)
        # Use canonical for API-based lookups
        all_results.extend(scan_all_platforms(canonical, max_results=max_results))

        # Also run platform scans for important non-quoted variants
        # (e.g., local phone format) to increase coverage
        key_variants = [v for v in variants if not v.startswith('"') and v != canonical]
        # Limit to top 3 key variants to avoid excessive requests
        for v in key_variants[:3]:
            logger.info("── Platform scan for variant: {} ──", v)
            all_results.extend(scan_all_platforms(v, max_results=max_results))
    else:
        logger.info("Skipping platforms (--skip-platforms)")

    # 4. Deduplicate by link
    seen_links: set[str] = set()
    unique_results: list[SearchResult] = []
    for r in all_results:
        if r.link and r.link not in seen_links:
            seen_links.add(r.link)
            unique_results.append(r)
            
    extended_info = {}

    # 5. Email search (Optional)
    if args.search_emails:
        logger.info("═" * 50)
        logger.info("Phase 3: Email Search")
        logger.info("═" * 50)
        
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
            "hibp": hibp_results
        }
        
    # 6. Network Checks (Optional)
    if args.network_scan:
        logger.info("═" * 50)
        logger.info("Phase 4: Network Enrichment")
        logger.info("═" * 50)
        # Note: active_ports set to False to keep it completely passive
        net_info = network_enrichment(unique_results, active_ports=False)
        extended_info["network"] = net_info

    logger.info("═" * 50)
    logger.info("Results Summary")
    logger.info("═" * 50)
    logger.info("Total raw results : {}", len(all_results))
    logger.info("After dedup       : {}", len(unique_results))
    if "emails" in extended_info:
        logger.info("Emails found      : {}", len(extended_info["emails"].get("dork_results", [])) + len(extended_info["emails"].get("extracted_from_platforms", [])))

    # 7. Report
    print_summary(unique_results)
    files = generate_reports(
        identifier=args.identifier,
        normalization=norm,
        results=unique_results,
        extended_info=extended_info,
        output_dir=output_dir,
    )

    elapsed = time.monotonic() - start
    logger.info("─" * 50)
    logger.info("Scan completed in {:.1f}s", elapsed)
    logger.info("JSON → {}", files["json_path"])
    logger.info("CSV  → {}", files["csv_path"])
    logger.info("SHA  → {}", files["manifest_path"])


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
