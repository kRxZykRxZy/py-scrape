"""Public contact/website enrichment for ARMv7/Pi 2.

Uses configured English/UK SearXNG instances sequentially, inspects public
first-party pages, and optionally uses the free Pollinations text endpoint as
an advisory verifier. It never invents contact details.
"""
import re, html, json, os, urllib.parse, urllib.request
from urllib.error import HTTPError, URLError

TIMEOUT = float(os.getenv('ENRICH_TIMEOUT', '8'))
UA = 'py-scrape/1.6 (+public-contact-research)'
EMAIL_RE = re.compile(r"(?i)(?:mailto:)?([a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+)")
PHONE_RE = re.compile(r"(?<!\d)(?:\+44\s?\(?0?\)?|0)(?:\s?[1-9]\d{2,4})?(?:[\s.-]?\d){6,9}(?!\d)")
BAD_DOMAINS = {
    'google.com', 'google.co.uk', 'facebook.com', 'instagram.com',
    'linkedin.com', 'yelp.com', 'tripadvisor.co.uk', 'tripadvisor.com',
    'youtube.com', 'tiktok.com', 'x.com', 'yell.com', 'yell.co.uk',
    'checkatrade.com', 'trustpilot.com'
}
BAD_EMAIL_PARTS = ('example.', 'wixpress.', 'sentry.', 'wordpress.', 'cloudflare.', 'noreply@', 'no-reply@')

# The supplied monitoring table did not contain an instance explicitly marked
# Country=UK. The .uk endpoint below is retained as the default. In production,
# set SEARXNG_URLS to a comma-separated list of verified English/UK instances.
# They are always tested one-by-one; a timeout, error OR empty response causes
# the next instance to be tried.
DEFAULT_SEARXNG = ['https://search.undertale.uk/']
SEARXNG_URLS = [x.strip().rstrip('/') for x in os.getenv(
    'SEARXNG_URLS', ','.join(DEFAULT_SEARXNG)
).split(',') if x.strip()]
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
    """Try every configured SearXNG instance until useful results are returned."""
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
                # A live SearXNG instance returning zero results is not a useful
                # result for this lookup, so fail over to the next instance.
                if text.strip() or links:
                    return text, links
                continue
            except Exception:
                for raw in re.findall(r'href=[\"\']([^\"\']+)[\"\']', body, re.I):
                    raw = html.unescape(raw)
                    if raw.startswith(('http://', 'https://')):
                        links.append(raw)
                if links:
                    return body, links
                continue
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
    if compact_name and compact_name in compact_domain:
        return True
    if tokens and any(token in domain_words or token in compact_domain for token in tokens):
        return True
    visible_lower = visible.lower()
    return bool(tokens and sum(1 for token in tokens if token in visible_lower) >= max(1, min(2, len(tokens))))


def _contact_paths(base_url):
    parsed = urllib.parse.urlsplit(base_url)
    if not parsed.scheme or not parsed.netloc:
        return []
    root = f'{parsed.scheme}://{parsed.netloc}'
    paths = [
        '/contact-us/', '/contact/', '/contact', '/about-us/', '/about/', '/about',
        '/get-in-touch/', '/find-us/'
    ]
    return list(dict.fromkeys([base_url] + [root + path for path in paths]))


def _pollinations_json(prompt):
    """Call free text.pollinations.ai with no API key and parse a JSON object."""
    try:
        url = POLLINATIONS_URL + '/' + urllib.parse.quote(prompt, safe='')
        text, _, _ = _fetch(url, 30000, {
            'User-Agent': UA,
            'Accept': 'text/plain,text/html,application/json'
        })
        # Prefer the first JSON object in the model response; never use free-form
        # model text as contact data.
        match = re.search(r'\{.*?\}', text, re.S)
        if not match:
            return None
        return json.loads(match.group(0).replace('```json', '').replace('```', '').strip())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None


def _pollinations_verify(name, address, candidates):
    if not candidates:
        return None
    compact = '\n'.join(candidates[:15])
    prompt = (
        'Verify the official website for this UK business. '
        f'Business name: {name}. Address: {address}. Candidate URLs:\n{compact}\n'
        'Return ONLY JSON: {"website":"https://... or null","confidence":0}. '
        'Pick the official business website only. Reject Google Maps, social media, '
        'directories, review sites and unrelated businesses. If uncertain return null.'
    )
    data = _pollinations_json(prompt)
    if not isinstance(data, dict):
        return None
    site = data.get('website')
    try:
        confidence = int(data.get('confidence', 0))
    except Exception:
        return None
    if not isinstance(site, str) or confidence < 70 or not site.startswith(('http://', 'https://')):
        return None
    if _is_bad_domain(_domain(site)):
        return None
    return site


def _pollinations_email(name, address, evidence):
    """Select an email from supplied public evidence; the model may not invent one."""
    if not evidence:
        return None
    prompt = (
        'Find a public contact email for this UK business using ONLY the evidence below. '
        f'Business name: {name}. Address: {address}. Evidence:\n{evidence[:30000]}\n'
        'Return ONLY JSON: {"email":"name@example.co.uk or null","confidence":0}. '
        'Never invent an email. Return null if no email is explicitly present in the evidence.'
    )
    data = _pollinations_json(prompt)
    if not isinstance(data, dict):
        return None
    email = str(data.get('email') or '').lower().strip()
    try:
        confidence = int(data.get('confidence', 0))
    except Exception:
        return None
    if confidence < 70 or not EMAIL_RE.fullmatch(email):
        return None
    if any(x in email for x in BAD_EMAIL_PARTS) or _is_bad_domain(email.rsplit('@', 1)[1]):
        return None
    # Critical anti-hallucination check: the selected address must literally
    # occur in the public evidence supplied to the model.
    if email not in evidence.lower():
        return None
    return email


def enrich(row):
    name = str(row.get('name') or '').strip()
    address = str(row.get('address') or '').strip()
    outcode = str(row.get('postcode_district') or '').strip()
    if not name:
        return row

    # The final query is deliberately broad enough to catch sites whose contact
    # page is indexed but whose home page is not. This fixes cases such as
    # Accounts Aid -> accountsaid.co.uk/contact-us/.
    queries = [
        f'"{name}" "{outcode}" UK official website contact email',
        f'"{name}" "{address}" UK contact email',
        f'"{name}" {outcode} UK website',
        f'"{name}" {outcode} UK email "@"',
        f'"{name}" UK "contact-us" email',
    ]
    links = []
    evidence = []
    for query in queries:
        body, found_links = _searx(query)
        if body:
            evidence.append(body)
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

    seen = set()
    candidates = []
    for link in links:
        domain = _domain(link)
        if _is_bad_domain(domain) or domain in seen:
            continue
        seen.add(domain)
        candidates.append(link)

    # Inspect the candidate and common contact pages. This is intentionally
    # sequential and bounded for ARMv7/Pi 2.
    page_urls = []
    for candidate in candidates[:12]:
        page_urls.extend(_contact_paths(candidate))

    for link in list(dict.fromkeys(page_urls))[:36]:
        try:
            body, final, _ = _fetch(link)
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
        if body:
            evidence.append(body)
        if not row.get('email'):
            emails = _emails(body)
            if emails:
                row['email'] = emails[0]
        if not row.get('phone'):
            phones = _phones(body)
            if phones:
                row['phone'] = phones[0]
        domain = _domain(final)
        visible = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.unescape(body))).lower()
        if not row.get('website') and _looks_first_party(name, domain, visible):
            parsed = urllib.parse.urlsplit(final)
            row['website'] = f'{parsed.scheme}://{parsed.netloc}/'
        if row.get('email') and row.get('website'):
            break

    if candidates and not row.get('website'):
        verified = _pollinations_verify(name, address, candidates)
        if verified:
            row['website'] = verified

    # Use Pollinations only to choose among emails already found in the public
    # evidence. This makes the AI useful without allowing hallucinated contacts.
    if not row.get('email') and evidence:
        verified_email = _pollinations_email(name, address, '\n'.join(evidence))
        if verified_email:
            row['email'] = verified_email
    return row
