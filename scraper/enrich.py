"""Public contact/website enrichment for ARMv7/Pi 2.

Pipeline: SearXNG discovery -> direct public-page inspection -> optional
Pollinations legacy text endpoint as a final verifier. All network calls are
best-effort and time-limited so enrichment cannot stall a scrape indefinitely.
"""
import re,html,json,os,urllib.parse,urllib.request
from urllib.error import HTTPError,URLError
TIMEOUT=float(os.getenv('ENRICH_TIMEOUT','8'))
UA='py-scrape/1.3 (+public-contact-research)'
EMAIL_RE=re.compile(r"(?i)(?:mailto:)?([a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+)")
PHONE_RE=re.compile(r"(?<!\d)(?:\+44\s?\(?0?\)?|0)(?:\s?[1-9]\d{2,4})?(?:[\s.-]?\d){6,9}(?!\d)")
BAD_DOMAINS={'google.com','google.co.uk','facebook.com','instagram.com','linkedin.com','yelp.com','tripadvisor.co.uk','tripadvisor.com','youtube.com','tiktok.com','x.com'}
BAD_EMAIL_PARTS=('example.','wixpress.','sentry.','wordpress.','cloudflare.','noreply@','no-reply@')
# The supplied public list contains one UK-domain instance. Additional UK
# instances can be supplied through SEARXNG_URLS (comma separated). Instances
# are health-checked and tried one-by-one before moving to the next.
DEFAULT_SEARXNG=['https://search.undertale.uk/']
SEARXNG_URLS=[x.strip().rstrip('/') for x in os.getenv('SEARXNG_URLS',','.join(DEFAULT_SEARXNG)).split(',') if x.strip()]
POLLINATIONS_URL=os.getenv('POLLINATIONS_URL','https://text.pollinations.ai').rstrip('/')


def _fetch(url,limit=500000,headers=None):
 req=urllib.request.Request(url,headers=headers or {'User-Agent':UA,'Accept':'text/html,application/xhtml+xml'})
 with urllib.request.urlopen(req,timeout=TIMEOUT) as r:return r.read(limit).decode('utf-8','replace'),r.geturl(),dict(r.headers)

def _domain(url):
 try:return (urllib.parse.urlsplit(url).hostname or '').lower().removeprefix('www.')
 except Exception:return ''

def _searx(query):
 """Try configured SearXNG instances sequentially; return HTML/JSON text and links."""
 for base in SEARXNG_URLS:
  try:
   url=base+'/?q='+urllib.parse.quote(query)+'&format=json&language=en'
   body,final,_=_fetch(url,500000,{'User-Agent':UA,'Accept':'application/json,text/html'})
   links=[]
   try:
    data=json.loads(body)
    for r in data.get('results',[]):
     u=r.get('url') or r.get('link')
     if isinstance(u,str) and u.startswith('http'):links.append(u)
    # Keep result titles/content available for email extraction.
    text=' '.join(str(r.get(k,'')) for r in data.get('results',[]) for k in ('title','content','url'))
    return text,links
   except Exception:
    links=[]
    for raw in re.findall(r'href=["\']([^"\']+)["\']',body,re.I):
     raw=html.unescape(raw)
     if raw.startswith('http'):links.append(raw)
    return body,links
  except (HTTPError,URLError,TimeoutError,OSError,ValueError):
   continue
 return '',[]

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

def _pollinations_verify(name,address,links):
 """Ask the legacy no-key text endpoint to judge whether a candidate URL is
    actually the business website. This is deliberately only a verifier: if
    the endpoint is unavailable, normal deterministic checks remain authoritative.
    Current Pollinations documentation uses authenticated gen.pollinations.ai;
    text.pollinations.ai is retained here only as a best-effort legacy endpoint.
    """
 if not links:return None
 compact='\n'.join(links[:5])
 prompt=('You are a strict business website verifier. Business: %s. Address: %s. '
         'Candidate URLs:\n%s\nReturn ONLY JSON: {"website":"URL or null","confidence":0-100}. '
         'Choose a URL only if it clearly belongs to this exact business. Directory, '
         'social, maps and review sites are not the business website.'%(name,address,compact))
 try:
  url=POLLINATIONS_URL+'/'+urllib.parse.quote(prompt,safe='')
  text,_,_= _fetch(url,12000,{'User-Agent':UA,'Accept':'text/plain'})
  m=re.search(r'\{\s*"website"\s*:\s*(null|"[^"]*")\s*,\s*"confidence"\s*:\s*(\d+)\s*\}',text)
  if not m:return None
  site=None if m.group(1)=='null' else json.loads(m.group(1));conf=int(m.group(2))
  return site if site and conf>=80 else None
 except (HTTPError,URLError,TimeoutError,OSError,ValueError):
  return None

def enrich(row):
 name=str(row.get('name') or '').strip();address=str(row.get('address') or '').strip();outcode=str(row.get('postcode_district') or '').strip()
 if not name:return row
 queries=[f'"{name}" "{outcode}" email UK',f'"{name}" "{address}" email UK',f'"{name}" {outcode} contact email UK',f'"{name}" {outcode} "@" UK']
 links=[]
 for q in queries:
  body,ls=_searx(q);links.extend(ls)
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
 # Inspect likely first-party pages. A confirmed first-party site means this
 # lead should be excluded by maps.py because it is not actually website-free.
 for link in candidates[:8]:
  try:body,final,_=_fetch(link)
  except (HTTPError,URLError,TimeoutError,OSError):continue
  if not row.get('email'):
   es=_emails(body)
   if es:row['email']=es[0]
  if not row.get('phone'):
   ps=_phones(body)
   if ps:row['phone']=ps[0]
  d=_domain(final)
  visible=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html.unescape(body))).lower()
  if not row.get('website') and d and d not in BAD_DOMAINS and name.lower() in visible and not any(x in d for x in ('yell.com','yelp.','facebook.','instagram.','linkedin.','trustpilot.','google.')):
   row['website']=final
  if row.get('email') and row.get('website'):break
 if not row.get('website'):
  verified=_pollinations_verify(name,address,candidates)
  if verified:row['website']=verified
 return row
