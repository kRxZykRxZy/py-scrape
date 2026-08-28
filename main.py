#!/usr/bin/env python3
"""py-scrape: lightweight London business lead collector.

Uses the Google Places API when GOOGLE_MAPS_API_KEY is configured. The API
approach is intentional: this project does not bypass CAPTCHAs or scrape
Google Maps' private web endpoints.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from scraper.maps import GooglePlacesClient
from scraper.postcode import validate_london_postcode
from scraper.contacts import enrich_business


def ask_count() -> int:
    while True:
        raw = input("How many businesses? ").strip()
        try:
            value = int(raw)
            if 1 <= value <= 1000:
                return value
        except ValueError:
            pass
        print("Enter a number between 1 and 1000.")


def main() -> int:
    print("\n=== py-scrape | London Business Finder ===\n")
    postcode = input("London postcode district (e.g. UB10, NW10): ").strip().upper()
    try:
        postcode = validate_london_postcode(postcode)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    count = ask_count()
    key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        print("\nGOOGLE_MAPS_API_KEY is not set.")
        print("Set it before running, e.g. export GOOGLE_MAPS_API_KEY='...'")
        print("py-scrape deliberately uses the official Places API rather than CAPTCHA/anti-bot bypasses.")
        return 2

    client = GooglePlacesClient(key)
    print(f"\nSearching Google Places around {postcode}...")
    businesses = client.search(postcode, count)
    if not businesses:
        print("No businesses found.")
        return 0

    leads = []
    for i, business in enumerate(businesses, 1):
        print(f"[{i}/{len(businesses)}] {business.get('name', 'Unknown')}")
        enriched = enrich_business(business)
        if not enriched.get("website"):
            leads.append(enriched)
        if len(leads) >= count:
            break

    if not leads:
        print("\nNo businesses without a listed website were found in the returned results.")
        return 0

    Path("output").mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Z0-9-]", "", postcode)
    filename = Path("output") / f"{safe}_{datetime.now():%Y-%m-%d_%H%M%S}.csv"
    fields = ["business_name", "category", "address", "postcode", "phone", "email", "website", "rating", "reviews", "maps_url", "has_website", "lead_score", "scraped_at"]
    with filename.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads[:count])

    print(f"\nFound {len(leads[:count])} businesses without a listed website.")
    print(f"CSV saved: {filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
