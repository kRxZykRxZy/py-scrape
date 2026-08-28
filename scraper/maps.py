from __future__ import annotations

import time
from typing import Any

import requests


class GooglePlacesClient:
    """Small official Google Places API client.

    It searches text around a postcode and fetches place details. It does not
    automate a browser or attempt to evade Google's anti-bot controls.
    """

    SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

    def __init__(self, api_key: str, timeout: float = 15.0):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()

    def search(self, postcode: str, count: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_token = None
        while len(results) < count and len(results) < 100:
            params = {"query": f"businesses near {postcode}, London, UK", "key": self.api_key}
            if page_token:
                params["pagetoken"] = page_token
                time.sleep(2)
            response = self.session.get(self.SEARCH_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            status = payload.get("status")
            if status not in {"OK", "ZERO_RESULTS"}:
                raise RuntimeError(f"Google Places API error: {status} {payload.get('error_message', '')}".strip())
            for item in payload.get("results", []):
                place_id = item.get("place_id")
                if not place_id or place_id in seen:
                    continue
                seen.add(place_id)
                results.append(self.details(place_id, item))
                if len(results) >= count:
                    break
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return results

    def details(self, place_id: str, fallback: dict[str, Any]) -> dict[str, Any]:
        params = {
            "place_id": place_id,
            "fields": "name,formatted_address,address_components,formatted_phone_number,website,rating,user_ratings_total,url,types",
            "key": self.api_key,
        }
        response = self.session.get(self.DETAILS_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result", {})
        if not result:
            result = fallback
        postcode = ""
        for component in result.get("address_components", []):
            if "postal_code" in component.get("types", []):
                postcode = component.get("long_name", "")
                break
        return {
            "name": result.get("name", fallback.get("name", "")),
            "category": (result.get("types") or fallback.get("types") or [""])[0],
            "address": result.get("formatted_address", fallback.get("formatted_address", "")),
            "postcode": postcode,
            "phone": result.get("formatted_phone_number", ""),
            "website": result.get("website", ""),
            "rating": result.get("rating", ""),
            "reviews": result.get("user_ratings_total", ""),
            "maps_url": result.get("url", ""),
        }
