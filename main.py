from flask import Flask, request, jsonify, send_from_directory, Response
import csv, io, sqlite3, threading, time, os, uuid, re
from config import HOST, PORT, DB_PATH, MAX_LEADS, ALLOWED_STATUS
from health import check
app=Flask(__name__,static_folder='web/static',static_url_path='/static');os.makedirs(os.path.dirname(DB_PATH) or '.',exist_ok=True);DB_LOCK=threading.RLock();CONTROL=threading.Condition(DB_LOCK)
def db():
 c=sqlite3.connect(DB_PATH,timeout=30);c.row_factory=sqlite3.Row
 c.execute('''create table if not exists leads(id integer primary key autoincrement,job_id text,name text not null,category text,phone text,email text,address text,website text,status text default 'new',created_at text default current_timestamp)''')
 try:c.execute('alter table leads add column job_id text')
 except sqlite3.OperationalError:pass
 c.execute('''create table if not exists scrape_jobs(id text primary key,postcode text not null,target integer not null,found integer default 0,saved integer default 0,status text not null default 'queued',started_at real,finished_at real,error text default '',logs text default '')''');c.commit();return c
def log(c,jid,msg):
 r=c.execute('select logs from scrape_jobs where id=?',(jid,)).fetchone();old=r['logs'] if r else '';lines=(old+'\n'+time.strftime('%H:%M:%S ') + msg).strip().splitlines()[-300:];c.execute('update scrape_jobs set logs=? where id=?',('\n'.join(lines),jid));c.commit()
def _init_db():
 c=db();c.close()
_init_db()
@app.get('/')
def index():return send_from_directory('web','index.html')
@app.get('/health')
def health():
 try:return jsonify(check())
 except Exception as e:return jsonify(ok=False,error=str(e)),503
@app.get('/api/status')
def status():
 with DB_LOCK:
  c=db();total=c.execute('select count(*) from leads').fetchone()[0];jobs=[dict(x) for x in c.execute('select * from scrape_jobs order by coalesce(started_at,0) desc')];c.close()
 return jsonify(total=total,jobs=jobs,running=any(x['status'] in ('queued','running','paused') for x in jobs))
@app.get('/api/leads')
def leads():
 q=request.args.get('search','').strip();s=request.args.get('status','').strip();jid=request.args.get('job_id','').strip();w=[];p=[];sql='select * from leads'
 if jid:w.append('job_id=?');p.append(jid)
 if q:w.append('(name like ? or phone like ? or email like ? or address like ? or category like ?)');p += ['%'+q+'%']*5
 if s in ALLOWED_STATUS:w.append('status=?');p.append(s)
 if w:sql+=' where '+' and '.join(w)
 with DB_LOCK:c=db();rows=c.execute(sql+' order by id desc',p).fetchall();c.close()
 return jsonify(leads=[dict(x) for x in rows])
@app.post('/api/scrape')
def start():
 d=request.json or {};p=str(d.get('postcode','')).upper().strip()
 try:a=int(d.get('amount',0))
 except:a=0
 if not re.match(r'^(E|EC|N|NW|SE|SW|W|WC|EN|HA|IG|KT|RM|SM|UB|TW)\d',p):return jsonify(error='Enter a valid London postcode district, e.g. UB10 or NW10'),400
 if not 1<=a<=MAX_LEADS:return jsonify(error=f'Amount must be 1-{MAX_LEADS}'),400
 with DB_LOCK:
  c=db();active=c.execute('select count(*) from scrape_jobs where status in ("queued","running","paused")').fetchone()[0]
  if active>=3:c.close();return jsonify(error='Maximum 3 active sessions'),409
  jid=uuid.uuid4().hex[:12];c.execute('insert into scrape_jobs(id,postcode,target,status) values(?,?,?,"queued")',(jid,p,a));log(c,jid,f'Queued {p}, target {a}');c.close()
 return jsonify(ok=True,job_id=jid)
@app.post('/api/jobs/<jid>/pause')
def pause(jid):
 with DB_LOCK:
  c=db();r=c.execute('select status from scrape_jobs where id=?',(jid,)).fetchone()
  if not r:c.close();return jsonify(error='Session not found'),404
  if r['status'] not in ('running','queued'):c.close();return jsonify(error='Session cannot be paused'),409
  c.execute('update scrape_jobs set status="paused" where id=?',(jid,));log(c,jid,'Paused');c.close();CONTROL.notify_all()
 return jsonify(ok=True)
@app.post('/api/jobs/<jid>/resume')
def resume(jid):
 with DB_LOCK:
  c=db();r=c.execute('select * from scrape_jobs where id=?',(jid,)).fetchone()
  if not r:c.close();return jsonify(error='Session not found'),404
  if r['status']!='paused':c.close();return jsonify(error='Session is not paused'),409
  c.execute('update scrape_jobs set status="queued" where id=?',(jid,));log(c,jid,'Queued for resume');c.close();CONTROL.notify_all()
 return jsonify(ok=True)
@app.delete('/api/jobs/<jid>')
def delete_job(jid):
 with DB_LOCK:
  c=db();r=c.execute('select id,status from scrape_jobs where id=?',(jid,)).fetchone()
  if not r:c.close();return jsonify(error='Session not found'),404
  c.execute('delete from leads where job_id=?',(jid,));c.execute('delete from scrape_jobs where id=?',(jid,));c.commit();c.close();CONTROL.notify_all()
 return jsonify(ok=True)
@app.get('/api/export.csv')
def export():
 jid=request.args.get('job_id','').strip()
 with DB_LOCK:
  c=db();rows=c.execute('select * from leads'+(' where job_id=?' if jid else '')+' order by id desc',([jid] if jid else [])).fetchall();c.close()
 out=io.StringIO();w=csv.writer(out);w.writerow(rows[0].keys() if rows else ['id','job_id','name','category','phone','email','address','website','status','created_at']);w.writerows([tuple(r) for r in rows]);return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=leads.csv'})
@app.post('/api/leads')
def create():
 d=request.json or {};name=str(d.get('name','')).strip()
 if not name:return jsonify(error='Business name is required'),400
 s=d.get('status','new');s=s if s in ALLOWED_STATUS else 'new'
 with DB_LOCK:
  c=db();cur=c.execute('insert into leads(job_id,name,category,phone,email,address,website,status) values(?,?,?,?,?,?,?,?)',(d.get('job_id'),name,d.get('category',''),d.get('phone',''),d.get('email',''),d.get('address',''),d.get('website',''),s));c.commit();c.close()
 return jsonify(id=cur.lastrowid)
@app.patch('/api/leads/<int:i>')
def patch(i):
 d=request.json or {};s=d.get('status','new')
 if s not in ALLOWED_STATUS:return jsonify(error='Invalid status'),400
 with DB_LOCK:
  c=db();cur=c.execute('update leads set status=?,name=coalesce(?,name),phone=coalesce(?,phone),email=coalesce(?,email),address=coalesce(?,address),category=coalesce(?,category),website=coalesce(?,website) where id=?',(s,d.get('name'),d.get('phone'),d.get('email'),d.get('address'),d.get('category'),d.get('website'),i));c.commit();c.close()
 return jsonify(ok=cur.rowcount>0)
@app.delete('/api/leads/<int:i>')
def delete(i):
 with DB_LOCK:c=db();c.execute('delete from leads where id=?',(i,));c.commit();c.close()
 return jsonify(ok=True)
@app.post('/api/leads/bulk-delete')
def bulk():
 ids=(request.json or {}).get('ids',[])
 with DB_LOCK:c=db();c.executemany('delete from leads where id=?',[(int(i),) for i in ids]);c.commit();c.close()
 return jsonify(ok=True)
if __name__=='__main__':app.run(host=HOST,port=PORT)
