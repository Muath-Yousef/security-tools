"""
ID Exposure Scanner - Search Engines Module
Queries Google and Bing via legal HTTP scraping with polite random delays.
Includes retry logic for transient failures.
"""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from loguru import logger

from config import Config

# Module-level verbose flag (set by main.py)
VERBOSE = False


@dataclass
class SearchResult:
    """A single search-engine result."""
    source: str
    query: str
    title: str
    link: str
    snippet: str
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    max_retries: int | None = None,
    **kwargs,
) -> requests.Response | None:
    """
    Execute an HTTP request with automatic retry on transient errors.
    Returns the Response or None on total failure.
    """
    max_retries = max_retries if max_retries is not None else Config.MAX_RETRIES
    last_exc = None

    for attempt in range(1, max_retries + 2):  # +2 because first is attempt 1
        try:
            # Rotate User-Agent on each attempt
            hdrs = headers or Config.headers()
            hdrs["User-Agent"] = Config.random_user_agent()

            resp = requests.request(
                method, url,
                headers=hdrs,
                params=params,
                timeout=Config.REQUEST_TIMEOUT,
                **kwargs,
            )

            if VERBOSE:
                logger.debug("[HTTP] {} {} → {} ({} bytes)",
                             method.upper(), url, resp.status_code, len(resp.content))

            # 429 Too Many Requests → back off and retry
            if resp.status_code == 429:
                wait = min(2 ** attempt, 30)
                logger.warning("[HTTP] 429 rate-limited, backing off {}s (attempt {}/{})",
                               wait, attempt, max_retries + 1)
                time.sleep(wait)
                continue

            # 5xx → retry
            if resp.status_code >= 500:
                logger.warning("[HTTP] {} error, retrying (attempt {}/{})",
                               resp.status_code, attempt, max_retries + 1)
                time.sleep(2 * attempt)
                continue

            return resp

        except requests.Timeout:
            logger.warning("[HTTP] Timeout for {} (attempt {}/{})", url, attempt, max_retries + 1)
            last_exc = "timeout"
            time.sleep(2 * attempt)
        except requests.ConnectionError as exc:
            logger.warning("[HTTP] Connection error: {} (attempt {}/{})", exc, attempt, max_retries + 1)
            last_exc = str(exc)
            time.sleep(2 * attempt)
        except requests.RequestException as exc:
            logger.error("[HTTP] Fatal request error: {}", exc)
            return None

    logger.error("[HTTP] All {} retries exhausted for {} (last: {})", max_retries + 1, url, last_exc)
    return None


# ═══════════════════════════════════════════════════════════════
#  Google Search (HTML scraping)
# ═══════════════════════════════════════════════════════════════

def search_google(query: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Perform a Google search and return parsed results."""
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.google.com/search?q={encoded}&num={min(max_results, 20)}&hl=en"

    logger.info("[Google] Searching: {!r}", query)
    ts = _timestamp()

    resp = _request_with_retry("GET", url)
    if resp is None or not resp.ok:
        status = resp.status_code if resp else "no response"
        logger.error("[Google] Request failed (status: {})", status)
        Config.random_delay()
        return results

    if VERBOSE:
        logger.debug("[Google] Response size: {} bytes", len(resp.text))

    soup = BeautifulSoup(resp.text, "lxml")

    for div in soup.select("div.g")[:max_results]:
        a_tag = div.select_one("a[href]")
        if not a_tag:
            continue
        link = a_tag.get("href", "")
        if not link.startswith("http"):
            continue

        title_el = div.select_one("h3")
        title = title_el.get_text(strip=True) if title_el else ""

        snippet_el = div.select_one("div[data-sncf], span.st, div.VwiC3b")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

        results.append(SearchResult(
            source="google", query=query, title=title,
            link=link, snippet=snippet, timestamp=ts,
        ))

    logger.info("[Google] Found {} results for {!r}", len(results), query)
    Config.random_delay()
    return results


# ═══════════════════════════════════════════════════════════════
#  Bing Search (HTML scraping  /  optional API)
# ═══════════════════════════════════════════════════════════════

def search_bing(query: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Perform a Bing search. Uses API if BING_API_KEY is set, else HTML."""
    if Config.BING_API_KEY:
        return _search_bing_api(query, max_results=max_results)
    return _search_bing_html(query, max_results=max_results)


def _search_bing_html(query: str, *, max_results: int | None = None) -> list[SearchResult]:
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.bing.com/search?q={encoded}&count={min(max_results, 20)}"

    logger.info("[Bing/HTML] Searching: {!r}", query)
    ts = _timestamp()

    resp = _request_with_retry("GET", url)
    if resp is None or not resp.ok:
        logger.error("[Bing/HTML] Request failed")
        Config.random_delay()
        return results

    soup = BeautifulSoup(resp.text, "lxml")

    for li in soup.select("li.b_algo")[:max_results]:
        a_tag = li.select_one("h2 a[href]")
        if not a_tag:
            continue
        link = a_tag.get("href", "")
        title = a_tag.get_text(strip=True)

        snippet_el = li.select_one("div.b_caption p")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

        results.append(SearchResult(
            source="bing", query=query, title=title,
            link=link, snippet=snippet, timestamp=ts,
        ))

    logger.info("[Bing/HTML] Found {} results for {!r}", len(results), query)
    Config.random_delay()
    return results


def _search_bing_api(query: str, *, max_results: int | None = None) -> list[SearchResult]:
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []
    url = "https://api.bing.microsoft.com/v7.0/search"
    headers = {
        "Ocp-Apim-Subscription-Key": Config.BING_API_KEY,
        **Config.headers(),
    }
    params = {"q": query, "count": min(max_results, 50), "mkt": "en-US"}

    logger.info("[Bing/API] Searching: {!r}", query)
    ts = _timestamp()

    resp = _request_with_retry("GET", url, headers=headers, params=params)
    if resp is None or not resp.ok:
        logger.error("[Bing/API] Request failed")
        Config.random_delay()
        return results

    try:
        data = resp.json()
    except ValueError:
        logger.error("[Bing/API] Invalid JSON response")
        return results

    for item in data.get("webPages", {}).get("value", [])[:max_results]:
        results.append(SearchResult(
            source="bing_api", query=query,
            title=item.get("name", ""),
            link=item.get("url", ""),
            snippet=item.get("snippet", ""),
            timestamp=ts,
        ))

    logger.info("[Bing/API] Found {} results for {!r}", len(results), query)
    Config.random_delay()
    return results

# ═══════════════════════════════════════════════════════════════
#  Yahoo Search (HTML scraping - Free Fallback)
# ═══════════════════════════════════════════════════════════════

def search_yahoo(query: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Perform a Yahoo search and return parsed results (useful fallback when Google blocks)."""
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []
    encoded = urllib.parse.quote_plus(query)
    url = f"https://search.yahoo.com/search?p={encoded}&n={min(max_results, 30)}"

    logger.info("[Yahoo] Searching: {!r}", query)
    ts = _timestamp()

    headers = Config.headers()
    resp = _request_with_retry("GET", url, headers=headers)
    
    if resp is None or not resp.ok:
        status = resp.status_code if resp else "no response"
        logger.error("[Yahoo] Request failed (status: {})", status)
        Config.random_delay()
        return results

    soup = BeautifulSoup(resp.text, "lxml")

    for div in soup.select("div.algo, div.algo-sr")[:max_results]:
        a_tag = div.select_one("h3.title a")
        if not a_tag:
            continue
        link = a_tag.get("href", "")
        if not link.startswith("http"):
            continue
        title = a_tag.get_text(strip=True)
        snippet_el = div.select_one("div.compText, div.compTitle, p.fc-falcon")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

        results.append(SearchResult(
            source="yahoo", query=query, title=title,
            link=link, snippet=snippet, timestamp=ts,
        ))

    logger.info("[Yahoo] Found {} results for {!r}", len(results), query)
    Config.random_delay()
    return results
