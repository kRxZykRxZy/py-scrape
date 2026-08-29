"""Public contact enrichment optimized for ARMv7/Pi 2."""
import re,html,urllib.parse,urllib.request
from urllib.error import HTTPError,URLError
TIMEOUT=8
UA='py-scrape/1.1 (+public-contact-research)'
EMAIL_RE=re.compile(r"(?i)(?:mailto:)?([a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+)")
PHONE_RE=re.compile(r"(?<!\d)(?:\+44\s?\(?0?\)?|0)(?:\s?[1-9]\d{2,4})?(?:[\s.-]?\d){6,9}(?!\d)")
BAD_DOMAINS={'google.com','google.co.uk','facebook.com','instagram.com','linkedin.com','yelp.com','tripadvisor.co.uk','tripadvisor.com','youtube.com','tiktok.com','x.com'}
BAD_EMAIL_PARTS=('example.','wixpress.','sentry.','wordpress.','cloudflare.','noreply@','no-reply@')

def _fetch(url,limit=500000):
 req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml'})
 with urllib.request.urlopen(req,timeout=TIMEOUT) as r:return r.read(limit).decode('utf-8','replace'),r.geturl()
def _domain(url):
 try:return (urllib.parse.urlsplit(url).hostname or '').lower().removeprefix('www.')
 except Exception:return ''
def _search(query):
 try:body,_=_fetch('https://html.duckduckgo.com/html/?q='+urllib.parse.quote(query),300000)
 except (HTTPError,URLError,TimeoutError,OSError):return '',[]
 links=[]
 for raw in re.findall(r'href=["\']([^"\']+)["\']',body,re.I):
  raw=html.unescape(raw)
  if 'uddg=' in raw:
   try:raw=urllib.parse.parse_qs(urllib.parse.urlsplit(raw).query).get('uddg',[''])[0]
   except Exception:pass
  if raw.startswith('http'):links.append(raw)
 return body,links
def _emails(text):
 out=[]
 for e in EMAIL_RE.findall(html.unescape(text)):
  e=e.lower().strip('.,;:)]\"')
  if not any(x in e for x in BAD_EMAIL_PARTS) and e not in out:out.append(e)
 return out
def _phones(text):
 out=[]
 for p in PHONE_RE.findall(html.unescape(text)):
  p=re.sub(r'\s+',' ',p).strip(' .-');digits=re.sub(r'\D','',p)
  if digits.startswith('44'):digits='0'+digits[2:]
  if 10<=len(digits)<=11 and digits.startswith('0') and p not in out:out.append(p)
 return out
def enrich(row):
 name=str(row.get('name') or '').strip();address=str(row.get('address') or '').strip();outcode=str(row.get('postcode_district') or '').strip()
 if not name:return row
 # Search several formulations. This catches emails published by directories,
 # social/business profiles and snippets even when the business has no website.
 queries=[f'"{name}" "{outcode}" email',f'"{name}" "{address}" email',f'"{name}" {outcode} contact email',f'"{name}" {outcode} "@"']
 links=[]
 for q in queries:
  body,ls=_search(q);links.extend(ls)
  if not row.get('email'):
   es=_emails(body)
   if es:row['email']=es[0]
  if not row.get('phone'):
   ps=_phones(body)
   if ps:row['phone']=ps[0]
  if row.get('email') and row.get('phone'):break
 seen=set();candidates=[]
 for link in links:
  d=_domain(link)
  if not d or d in BAD_DOMAINS or d in seen:continue
  seen.add(d);candidates.append(link)
 # Visit only a small number to remain practical on Pi 2.
 for link in candidates[:5]:
  try:body,final=_fetch(link)
  except (HTTPError,URLError,TimeoutError,OSError):continue
  if not row.get('email'):
   es=_emails(body)
   if es:row['email']=es[0]
  if not row.get('phone'):
   ps=_phones(body)
   if ps:row['phone']=ps[0]
  if not row.get('website'):
   d=_domain(final);visible=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html.unescape(body))).lower()
   if d and d not in BAD_DOMAINS and name.lower() in visible and not any(x in d for x in ('yell.com','yelp.','facebook.','instagram.','linkedin.','trustpilot.')):row['website']=final
  if row.get('email') and row.get('phone'):break
 return row
