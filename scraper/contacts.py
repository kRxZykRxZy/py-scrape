from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def _email_from_public_page(url: str) -> str:
    if not url:
        return ""
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "py-scrape/1.0"})
        if r.ok:
            match = EMAIL_RE.search(r.text)
            if match:
                return match.group(0)
    except requests.RequestException:
        pass
    return ""


def enrich_business(business: dict) -> dict:
    website = business.get("website", "") or ""
    email = ""
    if website:
        parsed = urlparse(website)
        base = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else website
        email = _email_from_public_page(website)
        if not email:
            email = _email_from_public_page(urljoin(base + "/", "contact"))
    score = 20
    if not website:
        score += 35
    if business.get("phone"):
        score += 15
    if email:
        score += 15
    rating = float(business.get("rating") or 0)
    reviews = int(business.get("reviews") or 0)
    if rating >= 4.5:
        score += 5
    if reviews >= 50:
        score += 10
    score = min(score, 100)
    return {
        "business_name": business.get("name", ""),
        "category": business.get("category", ""),
        "address": business.get("address", ""),
        "postcode": business.get("postcode", ""),
        "phone": business.get("phone", ""),
        "email": email,
        "website": website,
        "rating": business.get("rating", ""),
        "reviews": business.get("reviews", ""),
        "maps_url": business.get("maps_url", ""),
        "has_website": "yes" if website else "no",
        "lead_score": score,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
