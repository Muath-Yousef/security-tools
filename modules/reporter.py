"""
ID Exposure Scanner - Reporter Module
Generates JSON & CSV reports and provides SHA-256 integrity hashes.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

from config import Config
from modules.search_engines import SearchResult


def generate_reports(
    identifier: str,
    normalization: dict,
    results: list[SearchResult],
    *,
    extended_info: dict | None = None,
    output_dir: Path | None = None,
) -> dict[str, str]:
    """
    Write full JSON report and summary CSV, return dict of file paths and hashes.

    Returns:
        {
            "json_path": str,
            "csv_path":  str,
            "json_sha256": str,
            "csv_sha256":  str,
        }
    """
    output_dir = output_dir or Config.OUTPUT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_id = _safe_filename(identifier)
    base = f"scan_{safe_id}_{ts}"

    # ── JSON ──────────────────────────────────────────────────
    json_path = output_dir / f"{base}.json"
    report = {
        "meta": {
            "identifier": identifier,
            "normalization": normalization,
            "scan_timestamp": ts,
            "total_results": len(results),
        },
        "extended_info": extended_info or {},
        "results": [r.to_dict() for r in results],
    }
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    json_hash = _sha256(json_path)
    logger.info("JSON report saved → {} (SHA-256: {})", json_path, json_hash)

    # ── CSV ───────────────────────────────────────────────────
    csv_path = output_dir / f"{base}.csv"
    if results:
        df = pd.DataFrame([r.to_dict() for r in results])
        df.to_csv(csv_path, index=False, quoting=csv.QUOTE_ALL, encoding="utf-8")
    else:
        # Write header-only CSV
        csv_path.write_text("source,query,title,link,snippet,timestamp\n", encoding="utf-8")
    csv_hash = _sha256(csv_path)
    logger.info("CSV  report saved → {} (SHA-256: {})", csv_path, csv_hash)

    # ── Integrity manifest ────────────────────────────────────
    manifest_path = output_dir / f"{base}.sha256"
    manifest_path.write_text(
        f"{json_hash}  {json_path.name}\n{csv_hash}  {csv_path.name}\n",
        encoding="utf-8",
    )
    logger.info("Integrity manifest → {}", manifest_path)

    return {
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "json_sha256": json_hash,
        "csv_sha256": csv_hash,
        "manifest_path": str(manifest_path),
    }


def print_summary(results: list[SearchResult]) -> None:
    """Print a human-readable summary table to the console."""
    if not results:
        logger.info("No results found.")
        return

    # Count per source
    from collections import Counter
    counts = Counter(r.source for r in results)

    logger.info("┌────────────────────────┬───────┐")
    logger.info("│ Source                 │ Count │")
    logger.info("├────────────────────────┼───────┤")
    for source, count in sorted(counts.items()):
        logger.info("│ {:<22s} │ {:>5d} │", source, count)
    logger.info("├────────────────────────┼───────┤")
    logger.info("│ {:<22s} │ {:>5d} │", "TOTAL", len(results))
    logger.info("└────────────────────────┴───────┘")


# ── helpers ───────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_filename(text: str, max_len: int = 40) -> str:
    """Convert arbitrary text into a filesystem-safe string."""
    import re
    safe = re.sub(r"[^\w\-]", "_", text)
    return safe[:max_len].strip("_")
