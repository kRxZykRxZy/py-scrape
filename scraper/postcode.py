from __future__ import annotations

import re

# London postcode districts/prefixes accepted by the tool. The validator is
# intentionally conservative so the CLI cannot accidentally search elsewhere.
LONDON_PREFIXES = {
    "E", "EC", "N", "NW", "SE", "SW", "W", "WC", "BR", "CR", "DA", "EN",
    "HA", "IG", "KT", "RM", "SM", "TW", "UB", "WD",
}


def validate_london_postcode(value: str) -> str:
    value = re.sub(r"\s+", "", value.upper())
    match = re.fullmatch(r"([A-Z]{1,2})(\d{1,2}[A-Z]?)", value)
    if not match or match.group(1) not in LONDON_PREFIXES:
        raise ValueError("Use a London postcode district such as UB10, NW10, E1, N1, SW1 or W1.")
    return value
