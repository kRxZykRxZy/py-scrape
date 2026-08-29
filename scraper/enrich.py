"""Public contact/website enrichment for ARMv7/Pi 2.

Pipeline: UK-focused SearXNG discovery -> first-party/contact-page inspection ->
optional Pollinations no-key website verifier. All network calls are best-effort,
sequential and bounded so the Pi 2 stays responsive.
"""
import re, html, json, os, urllib.parse, urllib.request
from urllib.error import HTTPError, URLError

TIMEOUT = float(os.getenv('ENRICH_TIMEOUT', '8'))
UA = 'py-scrape/1.5 (+public-contact-research)'
EMAIL_RE = re.compile(r"(?i)(?:mailto:)?([a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+)")
PHONE_RE = re.compile(r"(?<!\d)(?:\+44\s?\(?0?\)?|0)(?:\s?[1-9]\d{2,4})?(?:[\s.-]?\d){6,9}(?!\d)")
BAD_DOMAINS = {
    'google.com', 'google.co.uk', 'facebook.com', 'instagram.com',
    'linkedin.com', 'yelp.com', 'tripadvisor.co.uk', 'tripadvisor.com',
    'youtube.com', 'tiktok.com', 'x.com', 'yell.com', 'yell.co.uk',
    'checkatrade.com', 'trustpilot.com'
}
BAD_EMAIL_PARTS = ('example.', 'wixpress.', 'sentry.', 'wordpress.', 'cloudflare.', 'noreply@', 'no-reply@')

# The supplied instance list contained one UK-hosted SearXNG URL. Keep it first,
# and allow the operator to add other UK/English instances through the environment.
DEFAULT_SEARXNG = ['https://search.undertale.uk/']
SEARXNG_URLS = [
    x.strip().rstrip('/')
    for x in os.getenv('SEARXNG_URLS', ','.join(DEFAULT_SEARXNG)).split(',')
    if x.strip()
]
POLLINATIONS_URL = os.getenv('POLLINATIONS_URL', 'https://text.pollinations.ai').rstrip('/')


def _fetch(url, limit=500000, headers=None):
    req = urllib.request.Request(
        url,
        headers=headers or {'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(limit).decode('utf-8', 'replace'), r.geturl(), dict(r.headers)


def _domain(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or '').lower().removeprefix('www.')
    except Exception:
        return ''


def _is_bad_domain(domain):
    return not domain or domain in BAD_DOMAINS or any(
        x in domain for x in (
            'yell.', 'yelp.', 'facebook.', 'instagram.', 'linkedin.',
            'trustpilot.', 'google.', 'tripadvisor.', 'checkatrade.'
        )
    )


def _searx(query):
    """Try configured English/UK SearXNG instances sequentially."""
    for base in SEARXNG_URLS:
        try:
            url = base + '/?q=' + urllib.parse.quote(query) + '&format=json&language=en&categories=general'
            body, _, _ = _fetch(url, 500000, {
                'User-Agent': UA,
                'Accept': 'application/json,text/html'
            })
            links = []
            try:
                data = json.loads(body)
                results = data.get('results', []) if isinstance(data, dict) else []
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    u = result.get('url') or result.get('link')
                    if isinstance(u, str) and u.startswith(('http://', 'https://')):
                        links.append(u)
                text = ' '.join(
                    str(result.get(k, ''))
                    for result in results if isinstance(result, dict)
                    for k in ('title', 'content', 'url')
                )
                return text, links
            except Exception:
                for raw in re.findall(r'href=[\"\']([^\"\']+)[\"\']', body, re.I):
                    raw = html.unescape(raw)
                    if raw.startswith(('http://', 'https://')):
                        links.append(raw)
                return body, links
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            continue
    return '', []


def _emails(text):
    out = []
    for email in EMAIL_RE.findall(html.unescape(text)):
        email = email.lower().strip('.,;:)]\"')
        if '@' not in email or any(x in email for x in BAD_EMAIL_PARTS):
            continue
        domain = email.rsplit('@', 1)[1]
        if _is_bad_domain(domain):
            continue
        if email not in out:
            out.append(email)
    return out


def _phones(text):
    out = []
    for phone in PHONE_RE.findall(html.unescape(text)):
        phone = re.sub(r'\s+', ' ', phone).strip(' .-')
        digits = re.sub(r'\D', '', phone)
        if digits.startswith('44'):
            digits = '0' + digits[2:]
        if 10 <= len(digits) <= 11 and digits.startswith('0') and phone not in out:
            out.append(phone)
    return out


def _business_tokens(name):
    return {
        x for x in re.findall(r'[a-z0-9]+', name.lower())
        if len(x) >= 3 and x not in {'ltd', 'limited', 'uk', 'the', 'and', 'co'}
    }


def _looks_first_party(name, domain, visible=''):
    if _is_bad_domain(domain):
        return False
    tokens = _business_tokens(name)
    compact_domain = re.sub(r'[^a-z0-9]', '', domain)
    compact_name = re.sub(r'[^a-z0-9]', '', name.lower())
    domain_words = set(re.findall(r'[a-z0-9]+', domain))

    # Handles branding such as "Accounts Aid" -> accountsaid.co.uk.
    if compact_name and compact_name in compact_domain:
        return True
    if tokens and any(token in domain_words or token in compact_domain for token in tokens):
        return True

    visible_lower = visible.lower()
    return bool(tokens and sum(1 for token in tokens if token in visible_lower) >= max(1, min(2, len(tokens))))


def _contact_paths(base_url):
    """Return likely contact/about pages for a candidate first-party site."""
    parsed = urllib.parse.urlsplit(base_url)
    if not parsed.scheme or not parsed.netloc:
        return []
    root = f'{parsed.scheme}://{parsed.netloc}'
    paths = [
        '/contact-us/', '/contact/', '/contact', '/about-us/', '/about/', '/about',
        '/get-in-touch/', '/find-us/'
    ]
    # Preserve the discovered URL first, then cheap common contact locations.
    return list(dict.fromkeys([base_url] + [root + path for path in paths]))


def _pollinations_verify(name, address, links):
    """Use free text.pollinations.ai as a best-effort website verifier.

    No API key is sent. The model is advisory only; deterministic domain checks
    remain authoritative when the model is unavailable or malformed.
    """
    if not links:
        return None
    compact = '\n'.join(links[:12])
    prompt = (
        'Verify the official website for this UK business. '
        f'Business name: {name}. Address: {address}. Candidate URLs:\n{compact}\n'
        'Return ONLY JSON: {"website":"https://... or null","confidence":0}. '
        'Pick the official business website only. Reject Google Maps, social media, '
        'directories, review sites and unrelated businesses. If uncertain return null.'
    )
    try:
        url = POLLINATIONS_URL + '/' + urllib.parse.quote(prompt, safe='')
        text, _, _ = _fetch(url, 20000, {
            'User-Agent': UA,
            'Accept': 'text/plain,text/html,application/json'
        })
        match = re.search(
            r'\{\s*[\"\']website[\"\']\s*:\s*(null|[\"\'][^\"\']+[\"\'])\s*,\s*'
            r'[\"\']confidence[\"\']\s*:\s*(\d+)',
            text, re.I | re.S
        )
        if not match:
            return None
        raw = match.group(1)
        site = None if raw.lower() == 'null' else raw.strip('\\\"\'')
        confidence = int(match.group(2))
        if not site or confidence < 70 or not site.startswith(('http://', 'https://')):
            return None
        domain = _domain(site)
        if _is_bad_domain(domain):
            return None
        return site
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None


def enrich(row):
    name = str(row.get('name') or '').strip()
    address = str(row.get('address') or '').strip()
    outcode = str(row.get('postcode_district') or '').strip()
    if not name:
        return row

    queries = [
        f'"{name}" "{outcode}" UK website email',
        f'"{name}" "{address}" UK contact email',
        f'"{name}" {outcode} UK email',
        f'"{name}" {outcode} UK "@"',
    ]
    links = []
    for query in queries:
        body, found_links = _searx(query)
        links.extend(found_links)
        if not row.get('email'):
            emails = _emails(body)
            if emails:
                row['email'] = emails[0]
        if not row.get('phone'):
            phones = _phones(body)
            if phones:
                row['phone'] = phones[0]
        if row.get('email') and row.get('phone'):
            break

    # De-duplicate by domain while retaining the first/best candidate.
    seen = set()
    candidates = []
    for link in links:
        domain = _domain(link)
        if _is_bad_domain(domain) or domain in seen:
            continue
        seen.add(domain)
        candidates.append(link)

    # Inspect the discovered business site AND its common contact pages.
    # This catches sites such as accountsaid.co.uk/contact-us/ even when the
    # SearXNG result points at another page on the same domain.
    page_urls = []
    for candidate in candidates[:12]:
        page_urls.extend(_contact_paths(candidate))

    for link in list(dict.fromkeys(page_urls))[:36]:
        try:
            body, final, _ = _fetch(link)
        except (HTTPError, URLError, TimeoutError, OSError):
            continue

        if not row.get('email'):
            emails = _emails(body)
            if emails:
                row['email'] = emails[0]
        if not row.get('phone'):
            phones = _phones(body)
            if phones:
                row['phone'] = phones[0]

        domain = _domain(final)
        visible = re.sub(
            r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.unescape(body))
        ).lower()
        if not row.get('website') and _looks_first_party(name, domain, visible):
            # Save the site's root, not a random contact-page URL.
            parsed = urllib.parse.urlsplit(final)
            row['website'] = f'{parsed.scheme}://{parsed.netloc}/'

        if row.get('email') and row.get('website'):
            break

    # Let Pollinations adjudicate remaining candidate websites. It is never
    # required for contact extraction, so a slow/down endpoint cannot stop a job.
    if candidates and not row.get('website'):
        verified = _pollinations_verify(name, address, candidates)
        if verified:
            row['website'] = verified

    return row
