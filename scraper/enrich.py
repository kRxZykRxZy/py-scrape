"""Public contact/website enrichment for ARMv7/Pi 2.

Pipeline: UK-focused SearXNG discovery -> public-page inspection -> optional
Pollinations no-key verifier. All network calls are best-effort and bounded.
"""
import re,html,json,os,urllib.parse,urllib.request
from urllib.error import HTTPError,URLError
TIMEOUT=float(os.getenv('ENRICH_TIMEOUT','8'))
UA='py-scrape/1.4 (+public-contact-research)'
EMAIL_RE=re.compile(r"(?i)(?:mailto:)?([a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+)")
PHONE_RE=re.compile(r"(?<!\d)(?:\+44\s?\(?0?\)?|0)(?:\s?[1-9]\d{2,4})?(?:[\s.-]?\d){6,9}(?!\d)")
BAD_DOMAINS={'google.com','google.co.uk','facebook.com','instagram.com','linkedin.com','yelp.com','tripadvisor.co.uk','tripadvisor.com','youtube.com','tiktok.com','x.com','yell.com'}
BAD_EMAIL_PARTS=('example.','wixpress.','sentry.','wordpress.','cloudflare.','noreply@','no-reply@')
# Default is deliberately UK-focused. Additional instances can be supplied with
# SEARXNG_URLS as a comma-separated allow-list; every instance is tried in order.
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
 """Try the configured English SearXNG instances sequentially."""
 for base in SEARXNG_URLS:
  try:
   url=base+'/?q='+urllib.parse.quote(query)+'&format=json&language=en&categories=general'
   body,final,_=_fetch(url,500000,{'User-Agent':UA,'Accept':'application/json,text/html'})
   links=[]
   try:
    data=json.loads(body)
    for r in data.get('results',[]):
     u=r.get('url') or r.get('link')
     if isinstance(u,str) and u.startswith('http'):links.append(u)
    text=' '.join(str(r.get(k,'')) for r in data.get('results',[]) for k in ('title','content','url'))
    return text,links
   except Exception:
    for raw in re.findall(r'href=[\"\']([^\"\']+)[\"\']',body,re.I):
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

def _business_tokens(name):
 return {x for x in re.findall(r'[a-z0-9]+',name.lower()) if len(x)>=3 and x not in {'ltd','limited','uk','the','and','co'} }

def _looks_first_party(name,domain,visible=''):
 if not domain or domain in BAD_DOMAINS:return False
 if any(x in domain for x in ('yell.','yelp.','facebook.','instagram.','linkedin.','trustpilot.','google.','tripadvisor.')):return False
 tokens=_business_tokens(name)
 domain_words=set(re.findall(r'[a-z0-9]+',domain))
 # Domain match is useful when the site's branding uses a compact form, e.g.
 # Accounts Aid -> accountsaid.co.uk, even if the exact spaced name is absent.
 if tokens and (len(tokens & domain_words)>=1 or ''.join(sorted(tokens)) in domain.replace('.','')):
  return True
 return bool(tokens and sum(1 for t in tokens if t in visible.lower())>=max(1,min(2,len(tokens))))

def _pollinations_verify(name,address,links):
 """Use the free text.pollinations.ai endpoint as a best-effort verifier.

 No API key is sent. The model is never treated as authoritative when it is
 unavailable or returns malformed output; deterministic checks remain in force.
 """
 if not links:return None
 compact='\n'.join(links[:12])
 prompt=('Verify the official website for this UK business. Business name: %s. Address: %s. '
         'Candidate URLs:\n%s\nReturn ONLY JSON in this exact shape: '
         '{"website":"https://... or null","confidence":0}. '
         'Pick the official business website only. Reject Google Maps, social media, '
         'directories, review sites and unrelated businesses. If uncertain return null.'%(name,address,compact))
 try:
  url=POLLINATIONS_URL+'/'+urllib.parse.quote(prompt,safe='')
  text,_,_= _fetch(url,20000,{'User-Agent':UA,'Accept':'text/plain,text/html,application/json'})
  # Accept plain JSON, fenced JSON, or a JSON object embedded in model text.
  m=re.search(r'\{\s*[\"\']website[\"\']\s*:\s*(null|[\"\'][^\"\']+[\"\'])\s*,\s*[\"\']confidence[\"\']\s*:\s*(\d+)',text,re.I|re.S)
  if not m:return None
  raw=m.group(1)
  site=None if raw.lower()=='null' else raw.strip('\\\"\'')
  conf=int(m.group(2))
  if not site or conf<70 or not site.startswith(('http://','https://')):return None
  d=_domain(site)
  if d in BAD_DOMAINS or any(x in d for x in ('yell.','yelp.','facebook.','instagram.','linkedin.','trustpilot.','google.','tripadvisor.')):return None
  return site
 except (HTTPError,URLError,TimeoutError,OSError,ValueError):
  return None

def enrich(row):
 name=str(row.get('name') or '').strip();address=str(row.get('address') or '').strip();outcode=str(row.get('postcode_district') or '').strip()
 if not name:return row
 queries=[f'"{name}" "{outcode}" UK website email',f'"{name}" "{address}" UK contact',f'"{name}" {outcode} UK email',f'"{name}" {outcode} UK "@"']
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
 # De-duplicate result URLs/domains while retaining the best candidates.
 seen=set();candidates=[]
 for link in links:
  d=_domain(link)
  if not d or d in seen or d in BAD_DOMAINS:continue
  seen.add(d);candidates.append(link)
 # Inspect candidate pages for public contact information and first-party evidence.
 for link in candidates[:12]:
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
  if not row.get('website') and _looks_first_party(name,d,visible):row['website']=final
  if row.get('email') and row.get('website'):break
 # Always give Pollinations a chance to adjudicate the remaining candidates.
 if candidates and not row.get('website'):
  verified=_pollinations_verify(name,address,candidates)
  if verified:row['website']=verified
 return row
