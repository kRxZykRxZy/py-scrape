import re, urllib.parse, urllib.request
from config import POLLINATIONS_URL, REQUEST_TIMEOUT

def enrich(text):
    prompt=('Extract only publicly listed business contact data from this text. Return JSON-like fields: '
            'email, phone, website, contact_name, confidence. Never invent missing values.\n\n'+text[:8000])
    url=POLLINATIONS_URL.rstrip('/')+'/'+urllib.parse.quote(prompt,safe='')
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'py-scrape/1.0'})
        raw=urllib.request.urlopen(req,timeout=REQUEST_TIMEOUT).read().decode('utf-8','replace')
        email=re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',raw)
        phone=re.search(r'(?:\+44\s?\(?0?\d\)?[\d\s-]{7,}|0\d[\d\s-]{8,})',raw)
        return {'email':email.group(0) if email else '','phone':phone.group(0).strip() if phone else '','ai_raw':raw[:2000]}
    except Exception:
        return {'email':'','phone':'','ai_raw':''}
