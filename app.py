import csv, json, re, sqlite3, time, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlparse
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template, request

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'; EXPORTS = DATA / 'exports'
DATA.mkdir(exist_ok=True); EXPORTS.mkdir(exist_ok=True)
DB = DATA / 'py-scrape.db'
app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=3)
HEAD = {'User-Agent': 'py-scrape/2.0', 'Accept-Language': 'en-GB,en;q=0.8'}
YOLIST = 'https://yolist.uk/api/v1/businesses'
YOLIST_DETAIL = 'https://yolist.uk/api/v1/businesses/'
POSTCODES = 'https://api.postcodes.io/outcodes/'
OVERPASS = 'https://overpass-api.de/api/interpreter'
POLLINATIONS = 'https://text.pollinations.ai/'
CATEGORIES = ['accountant','builder','dentist','electrician','garage','hairdresser','landscaper','plumber','roofer','restaurant','solicitor','photographer','cleaning company','estate agent','auto repair','cafe','carpet cleaner','gardener','painter','locksmith']
DIRECTORIES = {'google.','facebook.','instagram.','yelp.','tripadvisor.','yell.com','thomsonlocal.','192.com','yellowpages.','checkatrade.','trustpilot.','linkedin.','youtube.','mapquest.','bing.com','apple.com','foursquare.','threebestrated.','nicelocal.','hotfrog.','freeindex.','cylex.','locallife.','firmania.','scoot.','uksmallbusinessdirectory.','businessmagnet.','touchlocal.'}

def db():
    c = sqlite3.connect(DB, timeout=30); c.row_factory = sqlite3.Row; return c

def init():
    c = db(); c.executescript('''CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,postcode TEXT NOT NULL,target INTEGER NOT NULL,status TEXT NOT NULL,found INTEGER DEFAULT 0,saved INTEGER DEFAULT 0,created REAL,updated REAL,log TEXT DEFAULT ""); CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,name TEXT,category TEXT,phone TEXT,email TEXT,address TEXT,source TEXT,website TEXT,UNIQUE(session_id,name,address));'''); c.commit(); c.close()
init()

def get_session(sid):
    c=db(); r=c.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone(); c.close(); return dict(r) if r else None

def log(sid,msg):
    c=db(); r=c.execute('SELECT log FROM sessions WHERE id=?',(sid,)).fetchone(); old=r['log'] if r else ''; c.execute('UPDATE sessions SET log=?,updated=? WHERE id=?',(old[-7000:]+time.strftime('[%H:%M:%S] ')+msg+'\n',time.time(),sid)); c.commit(); c.close()

def set_status(sid,status):
    c=db(); c.execute('UPDATE sessions SET status=?,updated=? WHERE id=?',(status,time.time(),sid)); c.commit(); c.close()

def clean(v): return BeautifulSoup(str(v or ''),'html.parser').get_text(' ',strip=True)

def slug(v): return re.sub(r'[^a-z0-9]+','-',str(v).lower()).strip('-')

def domain(url):
    try: return urlparse(url).netloc.lower().removeprefix('www.')
    except: return ''

def is_directory(url):
    d=domain(url); return not d or any(x in d for x in DIRECTORIES)

def get_json(url, params=None, timeout=12):
    try:
        r=requests.get(url, params=params, headers=HEAD, timeout=timeout); r.raise_for_status(); return r.json()
    except Exception: return None

def resolve_outcode(outcode, sid):
    data=get_json(POSTCODES + quote(outcode.upper()))
    if not data or not data.get('result'): raise RuntimeError('Could not resolve postcode district')
    r=data['result']; city=r.get('admin_district') or r.get('parish') or r.get('region') or ''
    lat=r.get('latitude'); lon=r.get('longitude')
    log(sid, f'Postcode {outcode} → {city} ({lat}, {lon})')
    return city, lat, lon

def yolist_search(city, category, page=1):
    # Yolist public API: no key/authentication; max 20 results/page and 60 req/min.
    return get_json(YOLIST, {'city':slug(city),'category':slug(category),'page':page,'limit':20}) or {}

def osm_search(lat, lon, category, radius=10000):
    terms = {'accountant':'office=accountant','builder':'craft=builder','dentist':'amenity=dentist','electrician':'craft=electrician','garage':'shop=car','hairdresser':'shop=hairdresser','landscaper':'craft=gardener','plumber':'craft=plumber','roofer':'craft=roofer','restaurant':'amenity=restaurant','solicitor':'office=lawyer','photographer':'craft=photographer','cleaning company':'craft=cleaning','estate agent':'office=estate_agent','auto repair':'shop=car_repair','cafe':'amenity=cafe','carpet cleaner':'craft=cleaning','gardener':'craft=gardener','painter':'craft=painter','locksmith':'craft=locksmith'}
    tag=terms.get(category,'')
    if not tag:return []
    k,v=tag.split('=',1)
    q=f'[out:json][timeout:25];(nwr["{k}"="{v}"](around:{radius},{lat},{lon}););out center tags;'
    try:
        r=requests.post(OVERPASS,data=q,headers=HEAD,timeout=30); r.raise_for_status(); return r.json().get('elements',[])
    except Exception:return []

def normalize_osm(x,category,outcode):
    t=x.get('tags',{}); name=t.get('name','').strip()
    if not name:return None
    address=' '.join(v for v in [t.get('addr:housenumber'),t.get('addr:street'),t.get('addr:city'),t.get('addr:postcode')] if v).strip()
    postcode=t.get('addr:postcode','').upper()
    if postcode and not postcode.startswith(outcode.upper()): return None
    return {'name':name,'category':category.title(),'phone':t.get('phone') or t.get('contact:phone') or '','email':t.get('email') or t.get('contact:email') or '','address':address or outcode.upper(),'source':'OpenStreetMap','website':t.get('website') or t.get('contact:website') or ''}

def normalize_yolist(x,category,outcode):
    addr=x.get('address') or {}; address=' '.join(v for v in [addr.get('line1'),addr.get('line2'),addr.get('postcode')] if v).strip()
    postcode=str(addr.get('postcode') or '').upper()
    if postcode and not postcode.startswith(outcode.upper()): return None
    return {'name':x.get('name','').strip(),'category':str(x.get('category') or category).title(),'phone':x.get('phone') or '','email':x.get('email') or '','address':address or outcode.upper(),'source':'Yolist','website':x.get('website') or '', 'slug':x.get('slug','')}

def detail_yolist(slug_value):
    if not slug_value:return {}
    return get_json(YOLIST_DETAIL + quote(slug_value)) or {}

def pollinations(prompt):
    # Uses the requested public text endpoint; no API key, .env, or credentials are used.
    try:
        url=POLLINATIONS + quote(prompt)
        r=requests.get(url,params={'model':'gemini-search','json':'true'},headers=HEAD,timeout=15); r.raise_for_status()
        raw=r.text.strip()
        try:return json.loads(raw)
        except Exception:return raw
    except Exception:return None

def ai_verify(lead):
    prompt=('You are verifying a UK business lead. Return JSON only: {"is_business":true|false,"has_website":true|false,"phone":"","email":""}. '
            'Use only evidence in the supplied data; do not invent phone/email. If website evidence is absent, has_website must be false. '
            + json.dumps(lead,ensure_ascii=False))
    result=pollinations(prompt)
    if isinstance(result,dict):
        return result
    m=re.search(r'\{.*\}',str(result or ''),re.S)
    if m:
        try:return json.loads(m.group(0))
        except Exception:pass
    return {'is_business':True,'has_website':bool(lead.get('website')),'phone':lead.get('phone',''),'email':lead.get('email','')}

def enrich_with_ai(lead):
    # Ask the public search-capable Pollinations model to look for missing public contact/website evidence.
    prompt=('Find public evidence for this UK business and return JSON only with keys has_website,website,phone,email. '
            'Never invent data. If uncertain, use empty strings/false. Business: '+json.dumps({k:lead.get(k,'') for k in ['name','category','address']}))
    result=pollinations(prompt)
    if isinstance(result,dict): return result
    m=re.search(r'\{.*\}',str(result or ''),re.S)
    if m:
        try:return json.loads(m.group(0))
        except Exception:pass
    return {}

def export_csv(sid):
    c=db(); rows=[dict(r) for r in c.execute('SELECT name,category,phone,email,address,source FROM leads WHERE session_id=? ORDER BY id',(sid,))]; c.close(); p=EXPORTS/sid; p.mkdir(exist_ok=True); f=p/'leads.csv'
    with f.open('w',newline='',encoding='utf-8-sig') as h:
        w=csv.DictWriter(h,fieldnames=['name','category','phone','email','address','source']); w.writeheader(); w.writerows(rows)
    return f

def collect_category(city,lat,lon,category,outcode,sid):
    found=[]
    for page in range(1,6):
        data=yolist_search(city,category,page)
        items=data.get('businesses',[]) if isinstance(data,dict) else []
        for x in items:
            lead=normalize_yolist(x,category,outcode)
            if lead:
                d=detail_yolist(x.get('slug',''))
                if d:
                    lead['phone']=lead['phone'] or d.get('phone') or ''
                    lead['email']=lead['email'] or d.get('email') or ''
                    lead['website']=lead['website'] or d.get('website') or ''
                    a=d.get('address') or {}; lead['address']=' '.join(v for v in [a.get('line1'),a.get('line2'),a.get('postcode')] if v).strip() or lead['address']
                found.append(lead)
        if not items or page >= int(data.get('pages',page) or page): break
        if len(found)>=100: break
    for x in osm_search(lat,lon,category):
        lead=normalize_osm(x,category,outcode)
        if lead: found.append(lead)
    log(sid,f'{category}: collected {len(found)} candidates from Yolist + OpenStreetMap')
    return found

def scrape(sid):
    s=get_session(sid); outcode=s['postcode']; target=s['target']; set_status(sid,'running'); log(sid,f'Started: {outcode}, target {target}, 3 workers, no API keys')
    try:
        city,lat,lon=resolve_outcode(outcode,sid)
        candidates={}
        futures=[]
        for category in CATEGORIES:
            futures.append(executor.submit(collect_category,city,lat,lon,category,outcode,sid))
        for f in as_completed(futures):
            for lead in f.result():
                key=(re.sub(r'\W','',lead['name'].lower()),re.sub(r'\W','',lead['address'].lower()))
                if key not in candidates:candidates[key]=lead
            c=db(); c.execute('UPDATE sessions SET found=?,updated=? WHERE id=?',(len(candidates),time.time(),sid)); c.commit(); c.close()
            if len(candidates)>=target*2:
                break
        accepted=[]
        for lead in list(candidates.values()):
            s=get_session(sid)
            while s and s['status']=='paused': time.sleep(.5); s=get_session(sid)
            if not s or s['status']=='deleted': return
            # Website-free is based first on source fields, then an independent Pollinations verification.
            if lead.get('website'): continue
            extra=enrich_with_ai(lead)
            if extra.get('phone') and not lead.get('phone'): lead['phone']=str(extra['phone']).strip()
            if extra.get('email') and not lead.get('email'): lead['email']=str(extra['email']).strip()
            if extra.get('website'): continue
            check=ai_verify(lead)
            if check.get('has_website') is True: continue
            if check.get('is_business') is False: continue
            if check.get('phone') and not lead.get('phone'): lead['phone']=str(check['phone']).strip()
            if check.get('email') and not lead.get('email'): lead['email']=str(check['email']).strip()
            accepted.append(lead)
            if len(accepted)>=target: break
        c=db()
        for lead in accepted:
            try:c.execute('INSERT INTO leads(session_id,name,category,phone,email,address,source,website) VALUES(?,?,?,?,?,?,?,?)',(sid,lead['name'],lead['category'],lead['phone'],lead['email'],lead['address'],lead['source'],''))
            except sqlite3.IntegrityError:pass
        saved=c.execute('SELECT COUNT(*) n FROM leads WHERE session_id=?',(sid,)).fetchone()['n']; c.execute('UPDATE sessions SET status=?,saved=?,found=?,updated=? WHERE id=?',('completed',saved,len(candidates),time.time(),sid)); c.commit(); c.close(); export_csv(sid); log(sid,f'Completed: {saved} website-free leads saved to leads.csv')
    except Exception as e:
        log(sid,'Error: '+repr(e)); set_status(sid,'error')

@app.get('/')
def home(): return render_template('index.html')
@app.get('/api/sessions')
def sessions():
    c=db(); r=[dict(x) for x in c.execute('SELECT * FROM sessions ORDER BY created DESC')]; c.close(); return jsonify(r)
@app.post('/api/sessions')
def create():
    d=request.get_json() or {}; postcode=str(d.get('postcode','')).strip().upper()
    try: target=int(d.get('amount',0))
    except: target=0
    if not re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?',postcode) or not 1<=target<=1000:return jsonify(error='Use a UK postcode district such as UB10 or NW7, and 1–1000 leads.'),400
    sid=uuid.uuid4().hex[:10]; c=db(); c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?)',(sid,postcode,target,'queued',0,0,time.time(),time.time(),'')); c.commit(); c.close(); executor.submit(scrape,sid); return jsonify(id=sid)
@app.post('/api/sessions/<sid>/<action>')
def control(sid,action):
    if not get_session(sid):return jsonify(error='Session not found'),404
    if action not in ('pause','resume'):return jsonify(error='Invalid action'),400
    set_status(sid,'paused' if action=='pause' else 'running'); log(sid,action.title()); return jsonify(ok=True)
@app.delete('/api/sessions/<sid>')
def delete(sid):
    c=db(); c.execute('DELETE FROM leads WHERE session_id=?',(sid,)); c.execute('UPDATE sessions SET status=?,updated=? WHERE id=?',('deleted',time.time(),sid)); c.commit(); c.close(); return jsonify(ok=True)
@app.get('/api/sessions/<sid>/leads')
def leads(sid):
    c=db(); r=[dict(x) for x in c.execute('SELECT * FROM leads WHERE session_id=? ORDER BY id DESC',(sid,))]; c.close(); return jsonify(r)
@app.get('/api/sessions/<sid>/csv')
def csv_file(sid):
    p=export_csv(sid); return Response(p.read_bytes(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=leads.csv'})
@app.get('/health')
def health(): return {'ok':True}
