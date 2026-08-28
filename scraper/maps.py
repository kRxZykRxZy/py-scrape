"""Lightweight Google Places Text Search (New) client for ARMv7 Pi systems."""
import json
import os
import re
import time
import urllib.error
import urllib.request

API_URL = "https://places.googleapis.com/v1/places:searchText"
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
TIMEOUT = float(os.getenv("MAPS_TIMEOUT", "15"))
PAGE_SIZE = 20
POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$")
LONDON_PREFIXES = {"BR","CR","DA","E","EC","EN","HA","IG","KT","N","NW","RM","SE","SM","SW","TW","UB","W","WC"}


def validate_postcode(postcode):
    value = re.sub(r"\s+", "", postcode or "").upper()
    if not POSTCODE_RE.fullmatch(value):
        raise ValueError("Enter a London postcode district such as UB10 or NW10")
    prefix = re.match(r"^[A-Z]+", value).group(0)
    if prefix not in LONDON_PREFIXES:
        raise ValueError("Only London postcode districts are supported")
    return value


def _request(body):
    if not API_KEY:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured")
    request = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,places.types,places.businessStatus,nextPageToken",
        "User-Agent": "py-scrape/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError("Google Places API HTTP %s: %s" % (exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Google Places API connection failed: %s" % exc.reason) from exc


def _normalise(place):
    display = place.get("displayName") or {}
    types = place.get("types") or []
    return {
        "place_id": place.get("id", ""), "name": display.get("text", "").strip(),
        "category": types[0].replace("_", " ").title() if types else "",
        "phone": place.get("nationalPhoneNumber", "").strip(), "email": "",
        "address": place.get("formattedAddress", "").strip(),
        "website": place.get("websiteUri", "").strip(), "business_status": place.get("businessStatus", ""),
    }


def search_google_maps(postcode, amount):
    postcode = validate_postcode(postcode)
    amount = max(1, min(int(amount), 240))
    queries = ["businesses", "shops", "services", "companies"]
    results, seen = [], set()
    for kind in queries:
        token = None
        while len(results) < amount:
            body = {"textQuery": "%s in %s, London, UK" % (kind, postcode), "pageSize": PAGE_SIZE, "regionCode": "GB"}
            if token:
                body["pageToken"] = token
                time.sleep(1.5)
            response = _request(body)
            places = response.get("places", [])
            for raw in places:
                row = _normalise(raw); key = row["place_id"] or row["name"].lower()
                if not key or key in seen: continue
                seen.add(key); results.append(row)
                if len(results) >= amount: break
            token = response.get("nextPageToken")
            if not token or not places: break
        if len(results) >= amount: break
    return results[:amount]
