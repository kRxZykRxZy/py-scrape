"""Lightweight lead enrichment for Raspberry Pi / ARMv7.
Uses public web pages returned by DuckDuckGo HTML search and direct HTTP only.
Failures are non-fatal: a lead is still saved with verified Maps data.
"""
import re, html, urllib.parse, urllib.request
from urllib.error import HTTPError, URLError

TIMEOUT = 8
UA = 'py-scrape/1.0 (+lead-research)'
EMAIL_RE = re.compile(r'(?i)(?:mailto:)?([a-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+)')
URL_RE = re.compile(r'https?://[^\s<>"\']+')
BAD_DOMAINS = {'google.com','google.co.uk','facebook.com','instagram.com','linkedin.com','yelp.com','tripadvisor.co.uk','tripadvisor.com','youtube.com','tiktok.com'}


def _fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(700_000).decode('utf-8', 'replace'), r.geturl()


def _domain(url):
    try:
        return urllib.parse.urlsplit(url).hostname.lower().removeprefix('www.')
    except Exception:
        return ''


def _search(name, address):
    q = urllib.parse.quote('"%s" "%s"' % (name, address))
    url = 'https://html.duckduckgo.com/html/?q=' + q
    try:
        body, _ = _fetch(url)
    except (HTTPError, URLError, TimeoutError, OSError):
        return []
    # Extract result links conservatively; DDG may HTML-escape redirect URLs.
    links = []
    for raw in re.findall(r'href=["\']([^"\']+)["\']', body, re.I):
        raw = html.unescape(raw)
        if 'uddg=' in raw:
            try: raw = urllib.parse.parse_qs(urllib.parse.urlsplit(raw).query).get('uddg',[''])[0]
            except Exception: pass
        if raw.startswith('http'):
            links.append(raw)
    return links


def enrich(row):
    """Return row with best-effort public website/email enrichment."""
    name = str(row.get('name') or '').strip(); address = str(row.get('address') or '').strip()
    if not name: return row
    links = _search(name, address)
    candidates=[]; seen=set()
    for link in links:
        d=_domain(link)
        if not d or d in BAD_DOMAINS or d in seen: continue
        seen.add(d); candidates.append(link)
    # Only accept a domain as the business website after checking that its page
    # actually contains the business name. This prevents random directory results.
    for link in candidates[:4]:
        try:
            body, final = _fetch(link)
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
        text=re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',body))).lower()
        if name.lower() not in text and not any(part.lower() in text for part in name.split() if len(part)>3):
            continue
        row['website']=final
        emails=[]
        for e in EMAIL_RE.findall(body):
            e=e.lower().strip('.,;:')
            if e not in emails and not any(x in e for x in ('example.','wixpress.','sentry.','wordpress.')): emails.append(e)
        if emails: row['email']=emails[0]
        if not row.get('phone'):
            # Keep phone enrichment conservative; Maps is the primary source.
            m=re.search(r'(?:\+44\s?|0)(?:\d[\s.-]?){9,10}', text)
            if m: row['phone']=re.sub(r'\s+',' ',m.group(0)).strip()
        break
    return row
