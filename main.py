from flask import Flask, request, jsonify, send_from_directory, Response
import csv, io, sqlite3, threading, time, os, uuid
from config import HOST, PORT, DB_PATH, MAX_LEADS, ALLOWED_STATUS
from health import check

app = Flask(__name__, static_folder='web/static', static_url_path='/static')
os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
DB_LOCK = threading.RLock()

def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('''create table if not exists leads(id integer primary key autoincrement,name text not null,category text,phone text,email text,address text,website text,status text default 'new',created_at text default current_timestamp)''')
    c.execute('''create table if not exists scrape_jobs(id text primary key,postcode text not null,target integer not null,found integer default 0,saved integer default 0,status text not null default 'queued',started_at real,finished_at real,error text default '',logs text default '')''')
    c.commit(); return c

def job_log(c, jid, message):
    row = c.execute('select logs from scrape_jobs where id=?',(jid,)).fetchone(); old=row['logs'] if row else ''
    lines=(old+'\n'+time.strftime('%H:%M:%S ') + message).strip().splitlines()[-200:]
    c.execute('update scrape_jobs set logs=? where id=?',('\n'.join(lines),jid)); c.commit()

def save_row(c, r, seen):
    name=(r.get('name') or '').strip(); key=str(r.get('place_id') or name.lower()).lower()
    if not name or key in seen or r.get('website'): return False
    seen.add(key)
    c.execute('insert into leads(name,category,phone,email,address,website) values(?,?,?,?,?,?)',(name,r.get('category',''),r.get('phone',''),r.get('email',''),r.get('address',''),r.get('website','')))
    return True

def scrape_job(jid, postcode, amount):
    with DB_LOCK:
        c=db(); c.execute('update scrape_jobs set status="running",started_at=? where id=?',(time.time(),jid)); job_log(c,jid,f'Started {postcode}, target {amount}'); c.close()
    try:
        from scraper.maps import search_google_maps
        seen=set(); saved=0; found=0
        def on_result(r):
            nonlocal saved, found
            found += 1
            with DB_LOCK:
                c=db()
                if save_row(c,r,seen): saved += 1
                c.execute('update scrape_jobs set found=?,saved=? where id=?',(found,saved,jid)); c.commit(); c.close()
        rows=search_google_maps(postcode, amount, on_result=on_result)
        # Compatibility with older scraper implementations that don't invoke the callback.
        if not rows and found == 0:
            rows=[]
        with DB_LOCK:
            c=db(); c.execute('update scrape_jobs set status="complete",found=?,saved=?,finished_at=? where id=?',(found,saved,time.time(),jid)); job_log(c,jid,f'Finished: {saved} leads saved'); c.close()
    except Exception as e:
        with DB_LOCK:
            c=db(); c.execute('update scrape_jobs set status="error",error=?,finished_at=? where id=?',(str(e),time.time(),jid)); job_log(c,jid,'ERROR: '+str(e)); c.close()

def recover_jobs():
    # Browser refreshes never affect jobs. Jobs interrupted by a process/container restart are marked interrupted
    # rather than falsely appearing active; this keeps the UI truthful and the saved leads intact.
    c=db(); c.execute('update scrape_jobs set status="interrupted",finished_at=? where status in ("queued","running")',(time.time(),)); c.commit(); c.close()

with DB_LOCK: db().close(); recover_jobs()

@app.get('/')
def index(): return send_from_directory('web','index.html')
@app.get('/health')
def health():
    try: return jsonify(check())
    except Exception as e: return jsonify(ok=False,error=str(e)),503
@app.get('/api/status')
def status():
    with DB_LOCK:
        c=db(); total=c.execute('select count(*) from leads').fetchone()[0]; jobs=c.execute('select * from scrape_jobs order by started_at desc').fetchall(); c.close()
    return jsonify(total=total,jobs=[dict(x) for x in jobs],running=any(x['status'] in ('queued','running') for x in jobs))
@app.get('/api/jobs/<jid>')
def job(jid):
    with DB_LOCK:
        c=db(); row=c.execute('select * from scrape_jobs where id=?',(jid,)).fetchone(); c.close()
    if not row:return jsonify(error='Job not found'),404
    return jsonify(dict(row))
@app.get('/api/leads')
def leads():
    q=request.args.get('search','').strip(); s=request.args.get('status','').strip()
    with DB_LOCK:
        c=db(); sql='select * from leads'; params=[]; where=[]
        if q: where.append('(name like ? or phone like ? or email like ? or address like ? or category like ?)'); params += ['%'+q+'%']*5
        if s in ALLOWED_STATUS: where.append('status=?'); params.append(s)
        if where: sql+=' where '+' and '.join(where)
        rows=c.execute(sql+' order by id desc',params).fetchall(); c.close()
    return jsonify(leads=[dict(x) for x in rows])
@app.post('/api/scrape')
def start():
    d=request.json or {}; p=str(d.get('postcode','')).upper().strip()
    try:a=int(d.get('amount',0))
    except (TypeError,ValueError):a=0
    if not p or not 1<=a<=MAX_LEADS:return jsonify(error=f'Amount must be 1-{MAX_LEADS}'),400
    with DB_LOCK:
        c=db(); active=c.execute('select count(*) from scrape_jobs where status in ("queued","running")').fetchone()[0]
        if active>=3:c.close();return jsonify(error='Maximum 3 active scraping sessions'),409
        jid=uuid.uuid4().hex[:12]; c.execute('insert into scrape_jobs(id,postcode,target,status) values(?,?,?,"queued")',(jid,p,a)); c.commit(); c.close()
    threading.Thread(target=scrape_job,args=(jid,p,a),daemon=True,name='scrape-'+jid).start()
    return jsonify(ok=True,job_id=jid)
@app.post('/api/leads')
def create():
    d=request.json or {};name=str(d.get('name','')).strip()
    if not name:return jsonify(error='Business name is required'),400
    s=d.get('status','new');s=s if s in ALLOWED_STATUS else 'new'
    with DB_LOCK:
        c=db();cur=c.execute('insert into leads(name,category,phone,email,address,website,status) values(?,?,?,?,?,?,?)',(name,d.get('category',''),d.get('phone',''),d.get('email',''),d.get('address',''),d.get('website',''),s));c.commit();c.close()
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
    ids=request.json.get('ids',[])
    with DB_LOCK:c=db();c.executemany('delete from leads where id=?',[(int(i),) for i in ids]);c.commit();c.close()
    return jsonify(ok=True)
@app.post('/api/leads/bulk-status')
def bulk_status():
    d=request.json or {};s=d.get('status');ids=d.get('ids',[])
    if s not in ALLOWED_STATUS:return jsonify(error='Invalid status'),400
    with DB_LOCK:c=db();c.executemany('update leads set status=? where id=?',[(s,int(i)) for i in ids]);c.commit();c.close()
    return jsonify(ok=True)
@app.get('/api/export.csv')
def export():
    with DB_LOCK:c=db();rows=c.execute('select * from leads order by id desc').fetchall();c.close()
    out=io.StringIO();w=csv.writer(out);w.writerow(rows[0].keys() if rows else ['id','name','category','phone','email','address','website','status','created_at']);w.writerows([tuple(r) for r in rows])
    return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=leads.csv'})
if __name__=='__main__':app.run(host=HOST,port=PORT)
