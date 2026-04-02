"""
ID Exposure Scanner - Public Platforms Module
Queries public platforms for identifier exposure via legal HTTP/API methods.

Improvements over v1:
  - Paste sites updated (Ghostbin removed, active alternatives added)
  - Wayback Machine CDX URL search added
  - GitLab snippets endpoint added
  - DuckDuckGo HTML search (proper results, not just Instant Answer)
  - More regional Arabic/MENA platforms added
  - CAPTCHA detection imported from search_engines
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlencode, unquote

import requests
from bs4 import BeautifulSoup
from loguru import logger

from config import Config
from modules.search_engines import (
    SearchResult,
    _request_with_retry,
    _is_captcha_response,
    search_duckduckgo_html,
    VERBOSE,
)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════
#  GitHub  (Public API - no auth required, optional token)
# ═══════════════════════════════════════════════════════════════

def search_github(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Search GitHub code & users via the public REST API (v3)."""
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": Config.random_user_agent(),
    }
    if Config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {Config.GITHUB_TOKEN}"

    # ── Code search ──
    logger.info("[GitHub] Searching code for: {!r}", identifier)
    ts = _ts()
    resp = _request_with_retry(
        "GET", "https://api.github.com/search/code",
        headers=headers,
        params={"q": identifier, "per_page": min(max_results, 30)},
    )
    if resp and resp.status_code == 200:
        for item in resp.json().get("items", [])[:max_results]:
            results.append(SearchResult(
                source="github_code", query=identifier,
                title=item.get("name", ""),
                link=item.get("html_url", ""),
                snippet=item.get("repository", {}).get("full_name", ""),
                timestamp=ts,
            ))
    elif resp:
        logger.warning("[GitHub] Code search returned HTTP {}", resp.status_code)

    Config.random_delay()

    # ── User search ──
    logger.info("[GitHub] Searching users for: {!r}", identifier)
    ts = _ts()
    resp = _request_with_retry(
        "GET", "https://api.github.com/search/users",
        headers=headers,
        params={"q": identifier, "per_page": min(max_results, 30)},
    )
    if resp and resp.status_code == 200:
        for item in resp.json().get("items", [])[:max_results]:
            results.append(SearchResult(
                source="github_user", query=identifier,
                title=item.get("login", ""),
                link=item.get("html_url", ""),
                snippet=f"Score: {item.get('score', 'N/A')}",
                timestamp=ts,
            ))
    elif resp:
        logger.warning("[GitHub] User search returned HTTP {}", resp.status_code)

    logger.info("[GitHub] Total results: {}", len(results))
    Config.random_delay()
    return results


# ═══════════════════════════════════════════════════════════════
#  Reddit  (improved - proper User-Agent + OAuth fallback)
# ═══════════════════════════════════════════════════════════════

def search_reddit(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """
    Search Reddit. Uses OAuth if REDDIT_CLIENT_ID is set,
    otherwise uses old.reddit.com with proper headers.
    """
    if Config.REDDIT_CLIENT_ID and Config.REDDIT_CLIENT_SECRET:
        return _search_reddit_oauth(identifier, max_results=max_results)
    return _search_reddit_html(identifier, max_results=max_results)


def _search_reddit_html(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Scrape old.reddit.com search (more reliable than .json endpoint)."""
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []

    url = "https://old.reddit.com/search"
    headers = Config.headers()
    headers["User-Agent"] = "IDExposureScanner/2.0 (Security Assessment Tool)"

    logger.info("[Reddit] Searching: {!r}", identifier)
    ts = _ts()

    resp = _request_with_retry(
        "GET", url, headers=headers,
        params={"q": identifier, "sort": "relevance", "limit": str(min(max_results, 25))},
    )
    if resp is None or not resp.ok:
        status = resp.status_code if resp else "no response"
        logger.warning("[Reddit] HTML search returned {}", status)
        Config.random_delay()
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    for thing in soup.select("div.search-result-link")[:max_results]:
        a_tag = thing.select_one("a.search-title")
        if not a_tag:
            continue
        link = a_tag.get("href", "")
        if not link.startswith("http"):
            link = f"https://reddit.com{link}"
        title = a_tag.get_text(strip=True)

        snippet_el = thing.select_one("span.search-result-body")
        snippet = snippet_el.get_text(" ", strip=True)[:300] if snippet_el else ""

        results.append(SearchResult(
            source="reddit", query=identifier,
            title=title, link=link, snippet=snippet, timestamp=ts,
        ))

    logger.info("[Reddit] Found {} results", len(results))
    Config.random_delay()
    return results


def _search_reddit_oauth(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Use Reddit OAuth API (requires REDDIT_CLIENT_ID + SECRET)."""
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []

    logger.info("[Reddit/OAuth] Authenticating...")
    try:
        auth_resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(Config.REDDIT_CLIENT_ID, Config.REDDIT_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": "IDExposureScanner/2.0"},
            timeout=Config.REQUEST_TIMEOUT,
        )
        auth_resp.raise_for_status()
        token = auth_resp.json().get("access_token")
    except Exception as exc:
        logger.error("[Reddit/OAuth] Auth failed: {}", exc)
        return results

    logger.info("[Reddit/OAuth] Searching: {!r}", identifier)
    ts = _ts()
    resp = _request_with_retry(
        "GET", "https://oauth.reddit.com/search",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "IDExposureScanner/2.0",
        },
        params={"q": identifier, "limit": str(min(max_results, 25)), "sort": "relevance"},
    )
    if resp and resp.ok:
        for child in resp.json().get("data", {}).get("children", [])[:max_results]:
            post = child.get("data", {})
            results.append(SearchResult(
                source="reddit_api", query=identifier,
                title=post.get("title", ""),
                link=f"https://www.reddit.com{post.get('permalink', '')}",
                snippet=post.get("selftext", "")[:300],
                timestamp=ts,
            ))

    logger.info("[Reddit/OAuth] Found {} results", len(results))
    Config.random_delay()
    return results


# ═══════════════════════════════════════════════════════════════
#  GitLab  (Public API — code + snippets)
# ═══════════════════════════════════════════════════════════════

def search_gitlab(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Search GitLab public projects and snippets."""
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []

    # ── Project search ──
    logger.info("[GitLab] Searching projects: {!r}", identifier)
    ts = _ts()

    resp = _request_with_retry(
        "GET", "https://gitlab.com/api/v4/projects",
        params={"search": identifier, "per_page": min(max_results, 20)},
    )
    if resp and resp.ok:
        for project in resp.json()[:max_results]:
            results.append(SearchResult(
                source="gitlab_project", query=identifier,
                title=project.get("name_with_namespace", ""),
                link=project.get("web_url", ""),
                snippet=project.get("description", "") or "",
                timestamp=ts,
            ))

    Config.random_delay()

    # ── Snippet search (often overlooked, can contain leaked data) ──
    logger.info("[GitLab] Searching snippets: {!r}", identifier)
    ts = _ts()

    resp = _request_with_retry(
        "GET", "https://gitlab.com/api/v4/snippets",
        params={"search": identifier, "per_page": min(max_results, 20)},
    )
    if resp and resp.ok:
        for snippet in resp.json()[:max_results]:
            results.append(SearchResult(
                source="gitlab_snippet", query=identifier,
                title=snippet.get("title", ""),
                link=snippet.get("web_url", ""),
                snippet=snippet.get("description", "") or "",
                timestamp=ts,
            ))
    elif resp:
        logger.debug("[GitLab] Snippets search returned HTTP {}", resp.status_code)

    logger.info("[GitLab] Total results: {}", len(results))
    Config.random_delay()
    return results


# ═══════════════════════════════════════════════════════════════
#  DuckDuckGo  (HTML search — far richer than Instant Answer API)
# ═══════════════════════════════════════════════════════════════

def search_duckduckgo(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """
    DuckDuckGo HTML search (replaces the old Instant Answer API call).
    The IA API returned at most 1 result; HTML gives real SERP results.
    """
    return search_duckduckgo_html(identifier, max_results=max_results)


# ═══════════════════════════════════════════════════════════════
#  Wayback Machine CDX API
# ═══════════════════════════════════════════════════════════════

def search_wayback_machine(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """
    Search the Internet Archive CDX index for URLs containing the identifier.
    This finds pages that were indexed (and possibly later deleted) — very
    useful for catching leaked data that has since been taken down.
    """
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []

    logger.info("[Wayback] CDX URL search for: {!r}", identifier)
    ts = _ts()

    # The CDX API searches URLs (not full text) — still catches IDs that
    # appeared as URL path/query parameters (common in classifieds, forms).
    resp = _request_with_retry(
        "GET", "https://web.archive.org/cdx/search/cdx",
        params={
            "url": f"*{identifier}*",
            "output": "json",
            "limit": str(min(max_results, 30)),
            "fl": "original,timestamp,statuscode,mimetype",
            "filter": ["statuscode:200", "mimetype:text/html"],
            "collapse": "urlkey",
        },
    )
    if resp is None or not resp.ok:
        logger.warning("[Wayback] CDX search failed ({})",
                       resp.status_code if resp else "no response")
        Config.random_delay()
        return results

    try:
        rows = resp.json()
    except ValueError:
        Config.random_delay()
        return results

    if not rows or len(rows) < 2:
        Config.random_delay()
        return results

    # Row 0 is the column-header row
    col_names = rows[0]
    col = {name: idx for idx, name in enumerate(col_names)}

    for row in rows[1 : max_results + 1]:
        try:
            original_url = row[col["original"]]
            timestamp    = row[col["timestamp"]]
        except (KeyError, IndexError):
            continue

        archive_url = f"https://web.archive.org/web/{timestamp}/{original_url}"
        year = timestamp[:4] if len(timestamp) >= 4 else "?"

        results.append(SearchResult(
            source="wayback_machine",
            query=identifier,
            title=f"Archived: {original_url}",
            link=archive_url,
            snippet=f"URL contained identifier. Archived {year}. Original: {original_url}",
            timestamp=ts,
        ))

    logger.info("[Wayback] Found {} archived URLs containing identifier", len(results))
    Config.random_delay()
    return results


# ═══════════════════════════════════════════════════════════════
#  Social Media Google Dorking
# ═══════════════════════════════════════════════════════════════

def search_social_media(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """
    Use Google dorking to find the identifier on social media platforms.
    Targets: Facebook, Twitter/X, Instagram, LinkedIn, TikTok, Telegram,
             Snapchat, WhatsApp-link sites.
    """
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []

    platforms = [
        ("facebook",  "site:facebook.com"),
        ("twitter",   "site:twitter.com OR site:x.com"),
        ("instagram", "site:instagram.com"),
        ("linkedin",  "site:linkedin.com"),
        ("tiktok",    "site:tiktok.com"),
        ("telegram",  "site:t.me OR site:telegram.me"),
        ("snapchat",  "site:snapchat.com"),
        ("whatsapp",  "site:wa.me OR site:api.whatsapp.com"),
    ]

    for platform_name, site_filter in platforms:
        dork = f'"{identifier}" {site_filter}'
        logger.info("[Social/{}] Dorking: {}", platform_name, dork)
        ts = _ts()

        resp = _request_with_retry(
            "GET", "https://www.google.com/search",
            params={"q": dork, "num": min(max_results, 10), "hl": "en", "gl": "us"},
        )
        if resp is None or not resp.ok:
            logger.warning("[Social/{}] Google dork failed", platform_name)
            Config.random_delay()
            continue

        if _is_captcha_response(resp.text):
            logger.warning("[Social/{}] CAPTCHA detected — skipping", platform_name)
            Config.random_delay()
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        # Flexible container selector
        result_items = soup.select("div.g") or soup.select("div.tF2Cxc")

        for div in result_items[:max_results]:
            a_tag = div.select_one("a[href]")
            if not a_tag:
                continue
            link = a_tag.get("href", "")
            if not link.startswith("http"):
                continue
            title_el = div.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else ""
            snippet_el = (
                div.select_one("div.VwiC3b")
                or div.select_one("span.st")
                or div.select_one("div[data-sncf]")
            )
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

            results.append(SearchResult(
                source=f"social_{platform_name}", query=identifier,
                title=title, link=link, snippet=snippet, timestamp=ts,
            ))

        logger.info("[Social/{}] Found {} results so far", platform_name, len(results))
        Config.random_delay()

    return results


# ═══════════════════════════════════════════════════════════════
#  Local / Regional Platforms (MENA classifieds, forums)
# ═══════════════════════════════════════════════════════════════

def search_local_platforms(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Google dorking for local/regional platforms (classifieds, forums, real-estate)."""
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []

    sites = [
        ("opensooq",    "site:opensooq.com"),
        ("haraj",       "site:haraj.com.sa"),
        ("dubizzle",    "site:dubizzle.com OR site:bayut.com"),
        ("olx_mena",    "site:olx.com.eg OR site:olx.jo OR site:olx.sa"),
        ("waseet",      "site:waseet.net OR site:q8waseet.net"),
        ("yellowpages", "site:yellowpages.ae OR site:yellowpages.com.jo"),
        ("forums",      "site:arabteam2000.com OR site:vb.arabsgate.com"),
    ]

    for name, site_filter in sites:
        dork = f'"{identifier}" {site_filter}'
        logger.info("[Local/{}] Dorking: {}", name, dork)
        ts = _ts()

        resp = _request_with_retry(
            "GET", "https://www.google.com/search",
            params={"q": dork, "num": min(max_results, 10), "hl": "ar"},
        )
        if resp is None or not resp.ok:
            Config.random_delay()
            continue

        if _is_captcha_response(resp.text):
            logger.warning("[Local/{}] CAPTCHA detected — skipping", name)
            Config.random_delay()
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        result_items = soup.select("div.g") or soup.select("div.tF2Cxc")

        for div in result_items[:max_results]:
            a_tag = div.select_one("a[href]")
            if not a_tag:
                continue
            link = a_tag.get("href", "")
            if not link.startswith("http"):
                continue
            title_el = div.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else ""
            snippet_el = div.select_one("div.VwiC3b, span.st")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

            results.append(SearchResult(
                source=f"local_{name}", query=identifier,
                title=title, link=link, snippet=snippet, timestamp=ts,
            ))

        Config.random_delay()

    logger.info("[Local] Total: {} results", len(results))
    return results


# ═══════════════════════════════════════════════════════════════
#  Paste Sites
# ═══════════════════════════════════════════════════════════════

def search_pastebin_like(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """
    Search for pastes containing the identifier via Google dorking.

    Sites list updated v2:
      - Removed: Ghostbin (defunct since 2021)
      - Added: paste.fo, justpaste.it, rentry.co, privatebin.net,
               controlc.com, paste.gg
    """
    max_results = max_results or Config.MAX_RESULTS_PER_SOURCE
    results: list[SearchResult] = []

    dork = (
        f'"{identifier}" ('
        f'site:pastebin.com OR site:dpaste.org OR '
        f'site:paste.fo OR site:justpaste.it OR '
        f'site:rentry.co OR site:controlc.com OR '
        f'site:paste.gg OR site:hastebin.com'
        f')'
    )
    logger.info("[Paste] Dorking: {}", dork)
    ts = _ts()

    resp = _request_with_retry(
        "GET", "https://www.google.com/search",
        params={"q": dork, "num": min(max_results, 10), "hl": "en"},
    )
    if resp is None or not resp.ok:
        Config.random_delay()
        return results

    if _is_captcha_response(resp.text):
        logger.warning("[Paste] CAPTCHA detected")
        Config.random_delay()
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    result_items = soup.select("div.g") or soup.select("div.tF2Cxc")

    for div in result_items[:max_results]:
        a_tag = div.select_one("a[href]")
        if not a_tag:
            continue
        link = a_tag.get("href", "")
        if not link.startswith("http"):
            continue
        title_el = div.select_one("h3")
        title = title_el.get_text(strip=True) if title_el else ""
        snippet_el = div.select_one("div.VwiC3b, span.st")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

        results.append(SearchResult(
            source="paste_sites", query=identifier,
            title=title, link=link, snippet=snippet, timestamp=ts,
        ))

    logger.info("[Paste] Found {} results", len(results))
    Config.random_delay()
    return results


# ═══════════════════════════════════════════════════════════════
#  Truecaller-style lookup (API-based, requires key)
# ═══════════════════════════════════════════════════════════════

def search_truecaller(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """
    Truecaller API lookup (requires TRUECALLER_API_KEY in .env).
    Skipped automatically if no key is configured.
    """
    if not Config.TRUECALLER_API_KEY:
        logger.debug("[Truecaller] Skipped — no API key configured")
        return []

    results: list[SearchResult] = []
    logger.info("[Truecaller] Looking up: {!r}", identifier)
    ts = _ts()

    resp = _request_with_retry(
        "GET", "https://api4.truecaller.com/v1/search",
        headers={
            "Authorization": f"Bearer {Config.TRUECALLER_API_KEY}",
            "User-Agent": Config.random_user_agent(),
        },
        params={"q": identifier, "countryCode": "JO", "type": "4"},
    )
    if resp and resp.ok:
        try:
            data = resp.json()
            for entry in data.get("data", [])[:max_results]:
                name = entry.get("name", "")
                if isinstance(name, dict):
                    name = f"{name.get('first', '')} {name.get('last', '')}".strip()
                results.append(SearchResult(
                    source="truecaller", query=identifier,
                    title=name,
                    link=f"https://www.truecaller.com/search/jo/{identifier}",
                    snippet=f"Carrier: {entry.get('carrier', 'N/A')}",
                    timestamp=ts,
                ))
        except (ValueError, KeyError) as exc:
            logger.warning("[Truecaller] Parse error: {}", exc)
    elif resp:
        logger.warning("[Truecaller] HTTP {}", resp.status_code)

    logger.info("[Truecaller] Found {} results", len(results))
    Config.random_delay()
    return results


# ═══════════════════════════════════════════════════════════════
#  Aggregator – Run all platform checks
# ═══════════════════════════════════════════════════════════════

ALL_PLATFORM_SCANNERS = [
    search_github,
    search_reddit,
    search_gitlab,
    search_duckduckgo,       # now uses HTML search (richer results)
    search_wayback_machine,  # NEW: archived pages with ID in URL
    search_social_media,
    search_local_platforms,
    search_pastebin_like,
    search_truecaller,
]


def scan_all_platforms(identifier: str, *, max_results: int | None = None) -> list[SearchResult]:
    """Run every registered platform scanner and aggregate results."""
    combined: list[SearchResult] = []
    for scanner in ALL_PLATFORM_SCANNERS:
        try:
            combined.extend(scanner(identifier, max_results=max_results))
        except Exception as exc:
            logger.error("Scanner {} crashed: {}", scanner.__name__, exc)
    return combined
