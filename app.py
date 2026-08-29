import csv, json, re, sqlite3, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlparse
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template, request

BASE=Path(__file__).resolve().parent
DATA=BASE/'data'; EXPORTS=DATA/'exports'; DATA.mkdir(exist_ok=True); EXPORTS.mkdir(exist_ok=True)
DB=DATA/'py-scrape.db'; app=Flask(__name__); executor=ThreadPoolExecutor(max_workers=3)
SEARX_URL='https://searx.party'
HEAD={'User-Agent':'py-scrape/1.0','Accept-Language':'en-GB,en;q=0.8'}
CATEGORIES=['accountant','builder','dentist','electrician','garage','hairdresser','landscaper','plumber','roofer','restaurant','solicitor','photographer','cleaning company','estate agent','auto repair']
DIRECTORIES={'google.','facebook.','instagram.','yelp.','tripadvisor.','yell.com','thomsonlocal.','192.com','yellowpages.','checkatrade.','trustpilot.','linkedin.','youtube.','mapquest.','bing.com','apple.com','foursquare.','threebestrated.','nicelocal.','hotfrog.','freeindex.','cylex.','locallife.','firmania.','scoot.','uksmallbusinessdirectory.','businessmagnet.','touchlocal.'}

def db():
 c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row; return c

def init():
 c=db(); c.executescript('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,postcode TEXT NOT NULL,target INTEGER NOT NULL,status TEXT NOT NULL,found INTEGER DEFAULT 0,saved INTEGER DEFAULT 0,created REAL,updated REAL,log TEXT DEFAULT ""); CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,name TEXT,category TEXT,phone TEXT,email TEXT,address TEXT,source TEXT,website TEXT,UNIQUE(session_id,name,address));'); c.commit(); c.close()
init()

def get_session(sid):
 c=db(); r=c.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone(); c.close(); return dict(r) if r else None

def log(sid,msg):
 c=db(); r=c.execute('SELECT log FROM sessions WHERE id=?',(sid,)).fetchone(); old=r['log'] if r else ''; c.execute('UPDATE sessions SET log=?,updated=? WHERE id=?',(old[-7000:]+time.strftime('[%H:%M:%S] ')+msg+'\n',time.time(),sid)); c.commit(); c.close()

def set_status(sid,status):
 c=db(); c.execute('UPDATE sessions SET status=?,updated=? WHERE id=?',(status,time.time(),sid)); c.commit(); c.close()

def dom(u):
 try:return urlparse(u).netloc.lower().removeprefix('www.')
 except:return ''

def directory(u):
 d=dom(u); return not d or any(x in d for x in DIRECTORIES)

def searx(q):
 try:
  r=requests.get(SEARX_URL+'/search',params={'q':q,'format':'json','language':'en-GB','categories':'general'},headers=HEAD,timeout=10); r.raise_for_status(); return r.json().get('results',[])
 except Exception as e:return []

def all_search(q,sid):
 s=get_session(sid)
 while s and s['status']=='paused': time.sleep(.5); s=get_session(sid)
 if not s or s['status']=='deleted': return []
 rows=searx(q); log(sid,f'SearXNG: {SEARX_URL} → {len(rows)} results')
 return rows

def clean(v): return BeautifulSoup(str(v or ''),'html.parser').get_text(' ',strip=True)

def parse_result(x,postcode,category):
 title=clean(x.get('title')); url=x.get('url',''); text=clean(x.get('content'))
 if not title or not url or postcode.lower() not in (title+' '+text).lower(): return None
 name=re.split(r'\s+[|–—-]\s+',title)[0].strip()
 if not 2<=len(name)<=100:return None
 phones=re.findall(r'(?:\+44|0)(?:[\s().-]?\d){9,12}',text); emails=re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text)
 address=postcode.upper(); m=re.search(r'([^|.;]{2,80}\b(?:'+re.escape(postcode)+r')\b[^|.;]{0,40})',text,re.I)
 if m: address=m.group(1).strip(' ,')
 return {'name':name,'category':category.title(),'phone':re.sub(r'\s+',' ',phones[0]).strip() if phones else '','email':emails[0] if emails else '','address':address,'source':url}

def verify_no_website(name,postcode,sid):
 q=f'"{name}" "{postcode}" official website'
 for x in all_search(q,sid):
  u=x.get('url',''); title=clean(x.get('title')); text=clean(x.get('content'))
  if not u or directory(u): continue
  d=dom(u); n=re.sub(r'[^a-z0-9]','',name.lower()); dd=re.sub(r'[^a-z0-9]','',d)
  if n[:7] in dd or any(part in dd for part in n.split() if len(part)>4) or 'official website' in (title+' '+text).lower(): return False
 return True

def ai_check(lead):
 prompt='Return JSON only with keys likely_business and website_free. Do not invent facts. Assess this UK lead: '+json.dumps(lead)
 try:
  r=requests.get('https://text.pollinations.ai/'+quote(prompt),headers=HEAD,timeout=8); m=re.search(r'\{.*\}',r.text,re.S); j=json.loads(m.group(0)) if m else {}; return j.get('likely_business',True) is not False and j.get('website_free',True) is not False
 except Exception:return True

def export_csv(sid):
 c=db(); rows=[dict(r) for r in c.execute('SELECT name,category,phone,email,address,source FROM leads WHERE session_id=? ORDER BY id',(sid,))]; c.close(); p=EXPORTS/sid; p.mkdir(exist_ok=True); f=p/'leads.csv'
 with f.open('w',newline='',encoding='utf-8-sig') as h:
  w=csv.DictWriter(h,fieldnames=['name','category','phone','email','address','source']); w.writeheader(); w.writerows(rows)
 return f

def scrape(sid):
 s=get_session(sid); postcode=s['postcode']; target=s['target']; set_status(sid,'running'); log(sid,f'Started background scrape: {postcode}, target {target}')
 candidates={}
 try:
  for category in CATEGORIES:
   if len(candidates)>=target*2: break
   for x in all_search(f'{category} "{postcode}" UK',sid):
    lead=parse_result(x,postcode,category)
    if not lead: continue
    key=(lead['name'].lower(),lead['address'].lower())
    if key in candidates: continue
    candidates[key]=lead
    if len(candidates)>=target*2: break
   c=db(); c.execute('UPDATE sessions SET found=?,updated=? WHERE id=?',(len(candidates),time.time(),sid)); c.commit(); c.close()
  accepted=[]
  for lead in candidates.values():
   s=get_session(sid)
   while s and s['status']=='paused': time.sleep(.5); s=get_session(sid)
   if not s or s['status']=='deleted': return
   if verify_no_website(lead['name'],postcode,sid) and ai_check(lead): accepted.append(lead)
   if len(accepted)>=target: break
  c=db()
  for lead in accepted:
   try:c.execute('INSERT INTO leads(session_id,name,category,phone,email,address,source,website) VALUES(?,?,?,?,?,?,?,?)',(sid,lead['name'],lead['category'],lead['phone'],lead['email'],lead['address'],lead['source'],''))
   except sqlite3.IntegrityError:pass
  saved=c.execute('SELECT COUNT(*) n FROM leads WHERE session_id=?',(sid,)).fetchone()['n']; c.execute('UPDATE sessions SET status=?,saved=?,found=?,updated=? WHERE id=?',('completed',saved,len(candidates),time.time(),sid)); c.commit(); c.close(); export_csv(sid); log(sid,f'Completed: {saved} leads saved to leads.csv')
 except Exception as e: log(sid,'Error: '+repr(e)); set_status(sid,'error')

@app.get('/')
def home(): return render_template('index.html')
@app.get('/api/sessions')
def sessions():
 c=db(); r=[dict(x) for x in c.execute('SELECT * FROM sessions ORDER BY created DESC')]; c.close(); return jsonify(r)
@app.post('/api/sessions')
def create():
 d=request.get_json() or {}; postcode=str(d.get('postcode','')).strip().upper()
 try:target=int(d.get('amount',0))
 except:target=0
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
