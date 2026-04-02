"""
ID Exposure Scanner - Configuration Module
Loads environment variables and provides centralized configuration.
Includes rotating User-Agent and randomized delays.
"""

import os
import random
import time
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")

# Pool of realistic browser User-Agents for rotation
_USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


class Config:
    """Centralized configuration loaded from environment variables."""

    # HTTP
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "15"))
    REQUEST_DELAY_MIN: float = float(os.getenv("REQUEST_DELAY_MIN", "1.5"))
    REQUEST_DELAY_MAX: float = float(os.getenv("REQUEST_DELAY_MAX", "4.0"))
    MAX_RESULTS_PER_SOURCE: int = int(os.getenv("MAX_RESULTS_PER_SOURCE", "20"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "2"))

    # Output
    OUTPUT_DIR: Path = Path(os.getenv("OUTPUT_DIR", str(_PROJECT_ROOT / "output")))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Optional API keys
    BING_API_KEY: str | None = os.getenv("BING_API_KEY")
    GITHUB_TOKEN: str | None = os.getenv("GITHUB_TOKEN")
    REDDIT_CLIENT_ID: str | None = os.getenv("REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET: str | None = os.getenv("REDDIT_CLIENT_SECRET")
    TRUECALLER_API_KEY: str | None = os.getenv("TRUECALLER_API_KEY")
    HIBP_API_KEY: str | None = os.getenv("HIBP_API_KEY")
    @classmethod
    def random_user_agent(cls) -> str:
        """Return a randomly selected User-Agent string."""
        return random.choice(_USER_AGENTS)

    @classmethod
    def headers(cls) -> dict[str, str]:
        """Standard headers with a rotated User-Agent."""
        return {
            "User-Agent": cls.random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }

    @classmethod
    def random_delay(cls) -> None:
        """Sleep for a random duration between configured min/max."""
        delay = random.uniform(cls.REQUEST_DELAY_MIN, cls.REQUEST_DELAY_MAX)
        time.sleep(delay)
