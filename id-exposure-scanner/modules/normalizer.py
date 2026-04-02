"""
ID Exposure Scanner - Input Normalizer Module
Normalizes and generates format variants for an input identifier.
Includes smart phone-number detection for MENA region codes.
"""

from __future__ import annotations

import re
from loguru import logger

# Common MENA country codes   (code → local trunk digit)
_COUNTRY_CODES = {
    "962": "0",   # Jordan
    "966": "0",   # Saudi Arabia
    "971": "0",   # UAE
    "965": "",    # Kuwait (no trunk)
    "968": "",    # Oman
    "973": "",    # Bahrain
    "974": "",    # Qatar
    "961": "0",   # Lebanon
    "963": "0",   # Syria
    "964": "0",   # Iraq
    "970": "0",   # Palestine
    "20":  "0",   # Egypt
    "212": "0",   # Morocco
    "216": "",    # Tunisia
    "213": "0",   # Algeria
    "218": "0",   # Libya
    "249": "0",   # Sudan
    "967": "0",   # Yemen
    "1":   "",    # US/Canada
    "44":  "0",   # UK
}


def normalize(raw_identifier: str) -> dict:
    """
    Normalize the input identifier and produce search-ready variants.

    Returns a dict:
        {
            "original": str,
            "canonical": str,           # stripped & collapsed
            "variants": list[str],       # all unique search-ready forms
        }
    """
    original = raw_identifier.strip()
    logger.info("Normalizing identifier: {!r}", original)

    # --- Canonical form: remove all whitespace ---
    canonical = re.sub(r"\s+", "", original)

    variants: list[str] = []

    # 1. Canonical (no spaces)
    _add(variants, canonical)

    # 2. Extract pure digits
    digits_only = re.sub(r"\D", "", canonical)

    if digits_only and len(digits_only) >= 4:
        _add(variants, digits_only)

        # ── Phone-number intelligence ──
        _generate_phone_variants(digits_only, variants)

        # ── Generic groupings ──
        if len(digits_only) >= 7:
            _add(variants, _group(digits_only, "-"))
            _add(variants, _group(digits_only, " "))
            _add(variants, _group(digits_only, "."))

        if len(digits_only) >= 10:
            _add(variants, f"+{digits_only}")

    # 3. Keep original if different from canonical
    _add(variants, original)

    # 4. Quoted exact-match for each non-quoted variant
    for v in list(variants):
        if not v.startswith('"'):
            _add(variants, f'"{v}"')

    result = {
        "original": original,
        "canonical": canonical,
        "variants": variants,
    }
    logger.debug("Normalization result: {}", result)
    return result


def _generate_phone_variants(digits: str, variants: list[str]) -> None:
    """
    Generate locale-specific phone variants.

    Example for input "00962795714560":
        digits = "00962795714560"
        → detect country code 962 (Jordan)
        → local = 0795714560
        → international = +962795714560
        → variants: 0795714560, 795714560, +962795714560, +962-79-571-4560, etc.
    """
    # Strip leading 00 (international dialing prefix)
    clean = digits
    if clean.startswith("00"):
        clean = clean[2:]

    # Try to match a country code
    matched_cc = None
    remainder = None
    for cc in sorted(_COUNTRY_CODES.keys(), key=len, reverse=True):
        if clean.startswith(cc):
            matched_cc = cc
            remainder = clean[len(cc):]
            break

    if matched_cc and remainder and len(remainder) >= 6:
        trunk = _COUNTRY_CODES[matched_cc]
        local_number = trunk + remainder        # e.g. "0795714560"
        intl_no_plus = matched_cc + remainder   # e.g. "962795714560"

        logger.debug("Phone detected: CC={}, local={}, intl={}", matched_cc, local_number, intl_no_plus)

        # Core forms
        _add(variants, local_number)                         # 0795714560
        _add(variants, remainder)                            # 795714560
        _add(variants, f"+{intl_no_plus}")                   # +962795714560
        _add(variants, f"00{intl_no_plus}")                  # 00962795714560

        # Grouped: +962-79-571-4560  /  079-571-4560
        if len(remainder) >= 7:
            # Split local number into operator + subscriber
            op_len = 2 if len(remainder) >= 9 else 1
            operator = remainder[:op_len]
            subscriber = remainder[op_len:]
            sub_grouped = _group_subscriber(subscriber, "-")

            _add(variants, f"+{matched_cc}-{operator}-{sub_grouped}")
            _add(variants, f"+{matched_cc} {operator} {_group_subscriber(subscriber, ' ')}")
            if trunk:
                _add(variants, f"{trunk}{operator}-{sub_grouped}")
                _add(variants, f"{trunk}{operator} {_group_subscriber(subscriber, ' ')}")

        # WhatsApp-style: 962795714560 (no +, no 00)
        _add(variants, intl_no_plus)
    else:
        # Not a recognized phone — still try +/00 forms
        if len(digits) >= 10:
            _add(variants, f"+{digits}")
            _add(variants, f"00{digits}")


def _group_subscriber(sub: str, sep: str) -> str:
    """Group subscriber digits into 3-4 chunks."""
    n = len(sub)
    if n <= 3:
        return sub
    if n <= 4:
        return sub
    if n <= 7:
        return f"{sub[:3]}{sep}{sub[3:]}"
    return f"{sub[:3]}{sep}{sub[3:7]}{sep}{sub[7:]}" if n > 7 else f"{sub[:3]}{sep}{sub[3:]}"


# ── helpers ──

def _add(lst: list[str], value: str) -> None:
    """Append only if non-empty and not already present."""
    value = value.strip()
    if value and value not in lst:
        lst.append(value)


def _group(digits: str, sep: str) -> str:
    """Naively group a digit string into 3-4-4 / 3-3-4 chunks."""
    n = len(digits)
    if n <= 4:
        return digits
    if n <= 7:
        return f"{digits[:3]}{sep}{digits[3:]}"
    if n <= 10:
        return f"{digits[:3]}{sep}{digits[3:6]}{sep}{digits[6:]}"
    return f"{digits[:3]}{sep}{digits[3:6]}{sep}{digits[6:10]}{sep}{digits[10:]}"
