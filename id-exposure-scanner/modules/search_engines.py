"""
ID Exposure Scanner - Search Engines Module
Queries Google, Bing, Yahoo, and DuckDuckGo with robust fallbacks.
Includes CAPTCHA detection, multi-selector scraping, relevance scoring,
and URL normalization helpers.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote

import requests
from bs4 import BeautifulSoup
from loguru import logger

from config import Config

# Module-level verbose flag (set by main.py)
VERBOSE = False

# Tracking query parameters to strip during URL normalization
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "fbclid", "gclid", "gclsrc", "dclid", "msclkid",
    "ref", "source", "mc_cid", "mc_eid", "_hsenc", "_hsmi",
})

# Signals that indicate a CAPTCHA / anti-bot page
_CAPTCHA_SIGNALS = [
    "unusual traffic",
    "captcha",
    "verify you\u2019re a human",
    "verify you're a human",
    "i'm not a robot",
    "our systems have detected",
    "automated requests",
    "please solve",
    "are you a robot",
    "human verification",
]


@dataclass
class SearchResult:
    """A single search-engine result."""
    source: str
    query: str
    title: str
    link: str
    snippet: str
    timestamp: str = ""
    relevance_score: float = 0.0  # 0.0–1.0; computed post-collection

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_captcha_response(text: str) -> bool:
    """Return True if the page appears to be a CAPTCHA / bot-detection wall."""
    lower = text.lower()
    return any(signal in lower for signal in _CAPTCHA_SIGNALS)


def normalize_url(url: str) -> str:
    """
    Normalise a URL for accurate deduplication:
      - lowercase scheme + netloc
      - strip trailing slash on path
      - remove tracking query parameters
      - strip fragment
      - percent-decode unreserved characters
    """
    try:
        url = url.strip()
        parsed = urlparse(url)
        # Clean up query string
        if parsed.query:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            filtered = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
            clean_query = urlencode(filtered, doseq=True)
        else:
            clean_query = ""

        normalised = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            parsed.params,
            clean_query,
            "",  # strip fragment
        ))
        return normalised
    except Exception:
        return url


def score_result(result: SearchResult, identifier: str, variants: list[str]) -> float:
    """
    Score how relevant a result is to the searched identifier.
    Returns a score from 0.0 (no match) to 1.0 (strong match).

    Scoring weights:
      +0.50 — identifier found in the page title
      +0.25 — identifier found in the snippet
      +0.15 — digit sequence found anywhere in result text
      +0.10 — any search variant found in result text
    """
    id_lower = identifier.lower()
    title_lower = result.title.lower()
    snippet_lower = result.snippet.lower()
    full_text = f"{title_lower} {snippet_lower} {result.link.lower()}"
    score = 0.0

    # Exact identifier in title (highest weight)
    if id_lower in title_lower:
        score += 0.50

    # Exact identifier in snippet
    if id_lower in snippet_lower:
        score += 0.25

    # Digit-only match — finds phone numbers across format variations
    digits = re.sub(r"\D", "", identifier)
    if digits and len(digits) >= 6:
        text_digits = re.sub(r"\D", "", full_text)
        if digits in text_digits:
            score += 0.15

    # Any non-quoted variant found in full text
    for v in variants:
        v_clean = v.strip('"').lower()
        if len(v_clean) >= 6 and v_clean in full_text:
            score += 0.10
            break  # only award once

    return min(round(score, 2), 1.0)


# ═══════════════════════════════════════════════════════════════
#  HTTP retry wrapper
# ═══════════════════════════════════════════════════════════════

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

    for attempt in range(1, max_retries + 2):
        try:
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
                logger.debug("[HTTP] {} {} \u2192 {} ({} bytes)",
                             method.upper(), url, resp.status_code, len(resp.content))

            # 429 Too Many Requests → exponential back-off
            if resp.status_code == 429:
                wait = min(2 ** attempt, 60)
                logger.warning("[HTTP] 429 rate-limited, backing off {}s (attempt {}/{})",
                               wait, attempt, max_retries + 1)
                time.sleep(wait)
                continue

            # 5xx → retry with increasing delay
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
#  Google Search (HTML scraping with multi-selector fallback)
# ═══════════════════════════════════════════════════════════════

# CSS selectors tried in order — Google changes layout often
_GOOGLE_RESULT_SELECTORS = [
    "div.g",
    "div.tF2Cxc",
    "div.MjjYud > div",
    "div[data-hveid] > div > div",
]

_GOOGLE_SNIPPET_SELECTORS = [
    "div.VwiC3b",
    "div[data-sncf]",
    "span.st",
    "div.s",
    "div.IsZvec",
    "div[class*='snippet']",
]


def search_google(query: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Perform a Google search and return parsed results."""
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []
    encoded = urllib.parse.quote_plus(query)
    # gl=us keeps results in English; num capped at 20 by Google for HTML
    url = f"https://www.google.com/search?q={encoded}&num={min(max_results, 20)}&hl=en&gl=us"

    logger.info("[Google] Searching: {!r}", query)
    ts = _timestamp()

    resp = _request_with_retry("GET", url)
    if resp is None or not resp.ok:
        status = resp.status_code if resp else "no response"
        logger.error("[Google] Request failed (status: {})", status)
        Config.random_delay()
        return results

    # Detect CAPTCHA / bot-block before parsing
    if _is_captcha_response(resp.text):
        logger.warning(
            "[Google] CAPTCHA or bot-detection page returned — results will be empty. "
            "Consider adding a BING_API_KEY or waiting before retrying."
        )
        Config.random_delay()
        return results

    if VERBOSE:
        logger.debug("[Google] Response size: {} bytes", len(resp.text))

    soup = BeautifulSoup(resp.text, "lxml")

    # Try selector strategies in order until we get results
    result_items: list = []
    for selector in _GOOGLE_RESULT_SELECTORS:
        result_items = soup.select(selector)
        if result_items:
            logger.debug("[Google] Using selector: {!r} ({} items)", selector, len(result_items))
            break

    if not result_items:
        logger.warning("[Google] No result containers found — possible layout change or bot-block")

    for div in result_items[:max_results]:
        a_tag = div.select_one("a[href]")
        if not a_tag:
            continue
        link = a_tag.get("href", "")
        if not link.startswith("http"):
            continue

        title_el = div.select_one("h3")
        title = title_el.get_text(strip=True) if title_el else ""

        # Try snippet selectors in order
        snippet = ""
        for sel in _GOOGLE_SNIPPET_SELECTORS:
            snippet_el = div.select_one(sel)
            if snippet_el:
                snippet = snippet_el.get_text(" ", strip=True)
                break

        # Skip result containers with neither title nor snippet (ads/nav elements)
        if not title and not snippet:
            continue

        results.append(SearchResult(
            source="google", query=query, title=title,
            link=link, snippet=snippet, timestamp=ts,
        ))

    logger.info("[Google] Found {} results for {!r}", len(results), query)
    if not results and result_items:
        logger.warning("[Google] Containers found but no links extracted — scraper may need update")
    Config.random_delay()
    return results


# ═══════════════════════════════════════════════════════════════
#  Bing Search (HTML scraping / optional API)
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
    url = f"https://www.bing.com/search?q={encoded}&count={min(max_results, 20)}&setlang=en"

    logger.info("[Bing/HTML] Searching: {!r}", query)
    ts = _timestamp()

    resp = _request_with_retry("GET", url)
    if resp is None or not resp.ok:
        logger.error("[Bing/HTML] Request failed")
        Config.random_delay()
        return results

    if _is_captcha_response(resp.text):
        logger.warning("[Bing/HTML] CAPTCHA detected — results may be empty")
        Config.random_delay()
        return results

    soup = BeautifulSoup(resp.text, "lxml")

    for li in soup.select("li.b_algo")[:max_results]:
        a_tag = li.select_one("h2 a[href]")
        if not a_tag:
            continue
        link = a_tag.get("href", "")
        if not link.startswith("http"):
            continue
        title = a_tag.get_text(strip=True)

        # Bing snippet may be in multiple locations
        snippet_el = (
            li.select_one("div.b_caption p")
            or li.select_one("p.b_algoSlug")
            or li.select_one("div.b_snippet")
        )
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
    params = {"q": query, "count": min(max_results, 50), "mkt": "en-US", "safeSearch": "Off"}

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
    """Perform a Yahoo search and return parsed results."""
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []
    encoded = urllib.parse.quote_plus(query)
    url = f"https://search.yahoo.com/search?p={encoded}&n={min(max_results, 30)}&ei=UTF-8"

    logger.info("[Yahoo] Searching: {!r}", query)
    ts = _timestamp()

    headers = Config.headers()
    resp = _request_with_retry("GET", url, headers=headers)

    if resp is None or not resp.ok:
        status = resp.status_code if resp else "no response"
        logger.error("[Yahoo] Request failed (status: {})", status)
        Config.random_delay()
        return results

    if _is_captcha_response(resp.text):
        logger.warning("[Yahoo] CAPTCHA detected")
        Config.random_delay()
        return results

    soup = BeautifulSoup(resp.text, "lxml")

    # Yahoo uses multiple container class patterns across regions/layouts
    result_items = (
        soup.select("div.algo")
        or soup.select("div.algo-sr")
        or soup.select("div[class*='algo']")
    )

    for div in result_items[:max_results]:
        # Title link
        a_tag = (
            div.select_one("h3.title a")
            or div.select_one("h3 a")
            or div.select_one("a.ac-algo")
        )
        if not a_tag:
            continue
        link = a_tag.get("href", "")
        # Yahoo sometimes wraps links through a redirect
        if "r.search.yahoo.com" in link or not link.startswith("http"):
            continue
        title = a_tag.get_text(strip=True)

        snippet_el = (
            div.select_one("div.compText")
            or div.select_one("p.fc-falcon")
            or div.select_one("span.fc-falcon")
            or div.select_one("div.compTitle + div")
        )
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

        results.append(SearchResult(
            source="yahoo", query=query, title=title,
            link=link, snippet=snippet, timestamp=ts,
        ))

    logger.info("[Yahoo] Found {} results for {!r}", len(results), query)
    Config.random_delay()
    return results


# ═══════════════════════════════════════════════════════════════
#  DuckDuckGo HTML Search (much richer than Instant Answer API)
# ═══════════════════════════════════════════════════════════════

def search_duckduckgo_html(query: str, *, max_results: int | None = None) -> list[SearchResult]:
    """
    Scrape DuckDuckGo HTML search results.
    Returns real web results (unlike the Instant Answer API which only
    returns zero or one result for most queries).
    """
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []

    logger.info("[DDG/HTML] Searching: {!r}", query)
    ts = _timestamp()

    # html.duckduckgo.com is the non-JS endpoint
    resp = _request_with_retry(
        "GET", "https://html.duckduckgo.com/html/",
        params={"q": query, "kl": "us-en"},
        headers={
            **Config.headers(),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    if resp is None or not resp.ok:
        logger.warning("[DDG/HTML] Request failed")
        Config.random_delay()
        return results

    soup = BeautifulSoup(resp.text, "lxml")

    for result_div in soup.select("div.result, div.result__body")[:max_results]:
        a_tag = result_div.select_one("a.result__a")
        if not a_tag:
            continue

        raw_link = a_tag.get("href", "")
        # DDG HTML uses redirect links — extract actual URL from uddg param
        link = raw_link
        if "uddg=" in raw_link:
            qs = parse_qs(urlparse(raw_link).query)
            if "uddg" in qs:
                link = unquote(qs["uddg"][0])

        if not link.startswith("http"):
            continue

        title = a_tag.get_text(strip=True)
        snippet_el = result_div.select_one("a.result__snippet, div.result__snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

        results.append(SearchResult(
            source="duckduckgo_html", query=query,
            title=title, link=link, snippet=snippet, timestamp=ts,
        ))

    logger.info("[DDG/HTML] Found {} results for {!r}", len(results), query)
    Config.random_delay()
    return results
