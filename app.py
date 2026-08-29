import csv, io, json, os, re, sqlite3, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, url_for

BASE=Path(__file__).resolve().parent
DATA=BASE/'data'; DATA.mkdir(exist_ok=True)
DB=DATA/'py-scrape.db'; EXPORTS=DATA/'exports'; EXPORTS.mkdir(exist_ok=True)
app=Flask(__name__)
executor=ThreadPoolExecutor(max_workers=3)
locks={}

INSTANCES=[
 'https://searxng.website/','https://searxng.site/','https://searx.linxx.net/','https://searx.oloke.xyz/',
 'https://search.ctq.ro/','https://searxng.deggo.fyi/','https://search.mdosch.de/','https://searx.tiekoetter.com/',
 'https://find.xenorio.xyz/','https://grep.vim.wtf/','https://kantan.cat/','https://libresearch.space/',
 'https://search.ethibox.fr/','https://search.im-in.space/','https://search.indst.eu/','https://search.rhscz.eu/',
 'https://search.serpensin.com/','https://searx.ankha.ac/','https://searx.namejeff.xyz/','https://searx.thefloatinglab.world/',
 'https://www.gruble.de/','https://search.unredacted.org/','https://searx.ro/','https://search.zina.dev/',
 'https://search.2b9t.xyz/','https://search.anoni.net/','https://searx.dresden.network/','https://searxng.fishfvch.com/','https://searx.mbuf.net/','https://searx.perennialte.ch/'
]
HEAD={'User-Agent':'py-scrape/1.0 (+lead research tool)','Accept-Language':'en-GB,en;q=0.8'}
CATEGORIES=['accountant','builder','dentist','electrician','garage','hairdresser','landscaper','plumber','roofer','restaurant','solicitor','web designer','photographer','cleaning company','estate agent']

def db():
 c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row; return c

def init():
 c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,postcode TEXT NOT NULL,target INTEGER NOT NULL,status TEXT NOT NULL,found INTEGER DEFAULT 0,saved INTEGER DEFAULT 0,created REAL,updated REAL,log TEXT DEFAULT ''); CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,name TEXT,category TEXT,phone TEXT,email TEXT,address TEXT,source TEXT,website TEXT,UNIQUE(session_id,name,address));'''); c.commit(); c.close()
init()

def log(sid,msg):
 c=db(); r=c.execute('SELECT log FROM sessions WHERE id=?',(sid,)).fetchone(); old=r['log'] if r else ''; c.execute('UPDATE sessions SET log=?,updated=? WHERE id=?',(old[-7000:]+time.strftime('[%H:%M:%S] ')+msg+'\n',time.time(),sid)); c.commit(); c.close()

def session(sid):
 c=db(); r=c.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone(); c.close(); return dict(r) if r else None

def normalise_phone(v): return re.sub(r'\s+',' ',v or '').strip()
def valid_email(v): return bool(re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$',v or ''))
def domain(u):
 try:return urlparse(u).netloc.lower().removeprefix('www.')
 except:return ''
def has_website(url): return bool(domain(url)) and not any(x in domain(url) for x in ('google.','facebook.','instagram.','yelp.','tripadvisor.','yell.com','thomsonlocal.','192.com'))

def ai_check(name,category,address):
 prompt=f"Return JSON only: {{\"likely_local_business\":true,\"good_web_agency_lead\":true}}. Assess this UK business lead: name={name}; category={category}; address={address}. A good lead is a real local business that appears not to have its own website."
 try:
  r=requests.get('https://text.pollinations.ai/'+quote(prompt),timeout=8,headers=HEAD); text=r.text.strip(); m=re.search(r'\{.*\}',text,re.S); return json.loads(m.group(0)) if m else {'likely_local_business':True,'good_web_agency_lead':True}
 except Exception:return {'likely_local_business':True,'good_web_agency_lead':True}

def searx(instance,q):
 try:
  r=requests.get(instance.rstrip('/')+'/search',params={'q':q,'format':'json','language':'en-GB','categories':'general'},headers=HEAD,timeout=8); r.raise_for_status(); return r.json().get('results',[])
 except Exception:return []

def extract_result(x):
 title=BeautifulSoup(x.get('title',''),'html.parser').get_text(' ',strip=True); u=x.get('url',''); content=BeautifulSoup(x.get('content',''),'html.parser').get_text(' ',strip=True); return title,u,content

def parse_lead(title,url,content,postcode):
 text=' '.join([title,content]); name=title.split(' - ')[0].split(' | ')[0].strip()
 if not name or len(name)>120:return None
 phones=re.findall(r'(?:\+44\s?\(?0?\)?\s?|0)(?:\d[\s.-]?){8,11}\d',text)
 emails=re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',text)
 cats=[c for c in CATEGORIES if c in text.lower()]; category=cats[0].title() if cats else 'Local business'
 address='';
 m=re.search(r'([A-Z][A-Za-z .\'&-]{2,50},\s*(?:London|England|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}))',text)
 if m: address=m.group(1)
 if postcode.upper() not in text.upper() and postcode.lower() not in content.lower(): return None
 return {'name':name,'category':category,'phone':normalise_phone(phones[0]) if phones else '','email':emails[0] if emails and valid_email(emails[0]) else '','address':address or postcode.upper(),'source':url,'website':''}

def scrape(sid):
 s=session(sid); postcode=s['postcode']; target=s['target']; seen=set(); candidates=[]
 log(sid,f'Started 3-worker scrape for {postcode}, target {target}')
 queries=[f'{c} {postcode} UK' for c in CATEGORIES]
 try:
  for qi,q in enumerate(queries):
   if session(sid)['status']=='paused':
    while session(sid)['status']=='paused': time.sleep(.5)
   if session(sid)['status']=='deleted': return
   results=[]
   for inst in INSTANCES:
    results=searx(inst,q)
    if results:
     log(sid,f'SearXNG: {inst} returned {len(results)} results for {q}')
     break
   for x in results:
    title,url,content=extract_result(x)
    if not url or domain(url) in seen: continue
    lead=parse_lead(title,url,content,postcode)
    if not lead: continue
    # Reject pages where the business has a first-party website link in the search result.
    if has_website(url) and domain(url) not in {'google.com'}: continue
    key=(lead['name'].lower(),lead['address'].lower())
    if key in seen: continue
    seen.add(key); candidates.append(lead)
    if len(candidates)>=target*2: break
   c=db(); c.execute('UPDATE sessions SET found=?,updated=? WHERE id=?',(len(candidates),time.time(),sid)); c.commit(); c.close()
   if len(candidates)>=target*2: break
  # AI is a final heuristic only; it does not invent contact details.
  with ThreadPoolExecutor(max_workers=3) as pool:
   checks=list(pool.map(lambda x:ai_check(x['name'],x['category'],x['address']),candidates[:target*2]))
  c=db(); saved=0
  for lead,check in zip(candidates,checks):
   if saved>=target: break
   if not check.get('likely_local_business',True): continue
   try:
    c.execute('INSERT INTO leads(session_id,name,category,phone,email,address,source,website) VALUES(?,?,?,?,?,?,?,?)',(sid,lead['name'],lead['category'],lead['phone'],lead['email'],lead['address'],lead['source'],'')); saved+=1
   except sqlite3.IntegrityError: pass
  c.execute('UPDATE sessions SET status=?,saved=?,found=?,updated=? WHERE id=?',('completed',saved,len(candidates),time.time(),sid)); c.commit(); c.close(); log(sid,f'Completed: {saved} website-free leads saved')
 except Exception as e:
  log(sid,'Error: '+str(e)); c=db(); c.execute('UPDATE sessions SET status=?,updated=? WHERE id=?',('error',time.time(),sid)); c.commit(); c.close()

@app.get('/')
def home():
 return render_template('index.html')
@app.get('/api/sessions')
def sessions():
 c=db(); rows=[dict(r) for r in c.execute('SELECT * FROM sessions ORDER BY created DESC')]; c.close(); return jsonify(rows)
@app.post('/api/sessions')
def create_session():
 data=request.get_json() or {}; postcode=str(data.get('postcode','')).strip().upper(); target=int(data.get('amount',0))
 if not re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?$',postcode) or not 1<=target<=1000:return jsonify(error='Enter a valid UK postcode district and 1–1000 leads.'),400
 sid=uuid.uuid4().hex[:10]; c=db(); c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?)',(sid,postcode,target,'queued',0,0,time.time(),time.time(),'')); c.commit(); c.close(); locks[sid]=threading.Event(); executor.submit(scrape,sid); return jsonify(id=sid)
@app.post('/api/sessions/<sid>/<action>')
def action(sid,action):
 s=session(sid)
 if not s:return jsonify(error='Session not found'),404
 if action not in ('pause','resume'):return jsonify(error='Invalid action'),400
 status='paused' if action=='pause' else 'running'; c=db(); c.execute('UPDATE sessions SET status=?,updated=? WHERE id=?',(status,time.time(),sid)); c.commit(); c.close(); log(sid,status.title()); return jsonify(ok=True)
@app.delete('/api/sessions/<sid>')
def delete(sid):
 c=db(); c.execute('DELETE FROM leads WHERE session_id=?',(sid,)); c.execute('UPDATE sessions SET status=?,updated=? WHERE id=?',('deleted',time.time(),sid)); c.commit(); c.close(); return jsonify(ok=True)
@app.get('/api/sessions/<sid>/leads')
def leads(sid):
 c=db(); rows=[dict(r) for r in c.execute('SELECT * FROM leads WHERE session_id=? ORDER BY id DESC',(sid,))]; c.close(); return jsonify(rows)
@app.get('/api/sessions/<sid>/csv')
def csv_export(sid):
 rows=[]; c=db(); rows=[dict(r) for r in c.execute('SELECT name,category,phone,email,address,source FROM leads WHERE session_id=? ORDER BY id',(sid,))]; c.close(); out=io.StringIO(); w=csv.DictWriter(out,fieldnames=['name','category','phone','email','address','source']); w.writeheader(); w.writerows(rows); return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename=leads.csv'})
@app.get('/health')
def health():return {'ok':True}

if __name__=='__main__': app.run(host='0.0.0.0',port=81,threaded=True)
