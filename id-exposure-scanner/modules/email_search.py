"""
Email search module
- Extract emails from text
- Search for emails via Google dorking
- Check against HaveIBeenPwned (optional)
"""

import re
import requests
from typing import List, Dict, Optional
from loguru import logger
import time
import random

from config import Config
from .search_engines import SearchResult, _request_with_retry

def extract_emails_from_text(text: str) -> List[str]:
    """Extract email addresses from text."""
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    return list(set(re.findall(email_pattern, text)))

def search_emails_google_dork(identifier: str, variants: List[str], delay_range: tuple = (2, 5)) -> List[Dict]:
    """
    Search for email addresses related to identifier using Google dorking.
    Queries like: "@gmail.com" AND "0795714560"
    """
    results = []
    
    # For each variant, search for email patterns
    for variant in variants[:3]:  # limit variants to avoid rate-limit
        dorks = [
            f'"{variant}" "@gmail.com"',
            f'"{variant}" "@yahoo.com"',
            f'"{variant}" email',
            f'{variant} "email:"',
        ]
        for dork in dorks:
            logger.info("[EmailSearch] Dorking: {}", dork)
            try:
                url = f"https://www.google.com/search"
                params = {"q": dork, "num": 20, "hl": "en"}
                resp = _request_with_retry("GET", url, params=params)
                
                if resp and resp.status_code == 200:
                    # Simple extraction: look for email patterns in response text
                    emails = extract_emails_from_text(resp.text)
                    for email in emails:
                        results.append({
                            "source": "google_dork",
                            "query": dork,
                            "email": email,
                            "found_in": url
                        })
                Config.random_delay()
            except Exception as e:
                logger.debug(f"Email dork failed: {e}")
                
    # Deduplicate by email
    unique = {}
    for r in results:
        email = r['email']
        if email not in unique:
            unique[email] = r
    
    logger.info("[EmailSearch] Found {} unique emails via Dorking", len(unique))
    return list(unique.values())

def check_email_breaches(email: str, api_key: Optional[str] = None) -> Dict:
    """
    Check if email appears in breaches.
    Uses HaveIBeenPwned API if key is provided, otherwise falls back
    to leakcheck.io free public API.
    """
    if api_key:
        logger.info("[HIBP] Checking HaveIBeenPwned API for {}", email)
        try:
            headers = {
                'hibp-api-key': api_key,
                'User-Agent': Config.random_user_agent()
            }
            url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
            resp = _request_with_retry("GET", url, headers=headers)
            if resp and resp.status_code == 200:
                return {"email": email, "source": "hibp", "breaches": resp.json()}
            elif resp and resp.status_code == 404:
                return {"email": email, "source": "hibp", "breaches": []}
            else:
                status = resp.status_code if resp else "timeout"
                logger.warning("[HIBP] Returned {}", status)
        except Exception as e:
            logger.error("[HIBP] Check failed: {}", e)

    # Fallback / Free Alternative
    logger.info("[LeakCheck] Checking public API for {}", email)
    try:
        url = f"https://leakcheck.io/api/public?check={email}"
        resp = _request_with_retry("GET", url)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return {"email": email, "source": "leakcheck", "breaches": data.get("sources", [])}
            else:
                return {"email": email, "source": "leakcheck", "breaches": []}
        return {"email": email, "error": f"HTTP {resp.status_code}" if resp else "timeout"}
    except Exception as e:
        logger.error("[LeakCheck] Check failed: {}", e)
        return {"email": email, "error": str(e)}

def search_emails_from_platform_results(platform_results: List[SearchResult]) -> List[str]:
    """Extract emails from existing platform results."""
    all_emails = []
    for item in platform_results:
        text = str(item.title) + ' ' + str(item.snippet)
        emails = extract_emails_from_text(text)
        all_emails.extend(emails)
    
    res = list(set(all_emails))
    logger.info("[EmailSearch] Extracted {} emails from platform results", len(res))
    return res
