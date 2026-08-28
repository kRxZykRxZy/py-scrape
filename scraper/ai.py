from __future__ import annotations

import requests

BASE_URL = "https://text.pollinations.ai/"


def ask_ai(prompt: str, timeout: float = 12.0) -> str:
    """Optional lightweight AI helper using Pollinations' text endpoint."""
    try:
        response = requests.get(BASE_URL + requests.utils.quote(prompt, safe=""), timeout=timeout)
        if response.ok:
            return response.text.strip()
    except requests.RequestException:
        pass
    return ""


def classify_business(name: str, category: str) -> str:
    prompt = (
        "Return one short business category only (max 3 words). "
        f"Business: {name}. Existing category: {category}."
    )
    return ask_ai(prompt)[:80]


def suggest_outreach_angle(name: str, category: str) -> str:
    prompt = (
        "Give one concise, professional website-service sales angle for this local business. "
        f"Business: {name}; category: {category}. Max 18 words."
    )
    return ask_ai(prompt)[:300]
