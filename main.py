from flask import Flask, request, jsonify, send_from_directory, Response
import csv, io, sqlite3, threading, time, os
from config import HOST, PORT, DB_PATH, MAX_LEADS, ALLOWED_STATUS
from health import check

# Flask already owns the /static endpoint when static_folder is configured.
# Do not register another endpoint named `static` (it causes Gunicorn to fail).
app = Flask(__name__, static_folder='web/static', static_url_path='/static')
os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
state = {'running': False, 'state': 'idle', 'found': 0, 'saved': 0, 'logs': [], 'started_at': None}

def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute('''create table if not exists leads(id integer primary key autoincrement,name text not null,category text,phone text,email text,address text,website text,status text default 'new',created_at text default current_timestamp)''')
    c.commit()
    return c

def log(message):
    state['logs'].append(time.strftime('%H:%M:%S ') + message)
    state['logs'] = state['logs'][-200:]

def scrape(postcode, amount):
    state.update(running=True, state='scraping', found=0, saved=0, logs=[], started_at=time.time())
    log(f'Started {postcode}, target {amount}')
    try:
        from scraper.maps import search_google_maps
        rows = search_google_maps(postcode, amount)
        c = db(); seen = set()
        for r in rows:
            state['found'] += 1
            name = (r.get('name') or '').strip(); key = name.lower()
            if not name or key in seen or r.get('website'):
                continue
            seen.add(key)
            c.execute('insert into leads(name,category,phone,email,address,website) values(?,?,?,?,?,?)', (name, r.get('category',''), r.get('phone',''), r.get('email',''), r.get('address',''), r.get('website','')))
            state['saved'] += 1
        c.commit(); c.close(); log(f'Finished: {state["saved"]} leads saved')
    except Exception as e:
        log('ERROR: ' + str(e))
    finally:
        state['running'] = False; state['state'] = 'complete'

@app.get('/')
def index():
    return send_from_directory('web', 'index.html')

@app.get('/health')
def health():
    try: return jsonify(check())
    except Exception as e: return jsonify(ok=False, error=str(e)), 503

@app.get('/api/status')
def status():
    c=db(); state['total']=c.execute('select count(*) from leads').fetchone()[0]; c.close(); return jsonify(state)

@app.get('/api/leads')
def leads():
    q=request.args.get('search','').strip(); s=request.args.get('status','').strip(); c=db(); sql='select * from leads'; params=[]; where=[]
    if q: where.append('(name like ? or phone like ? or email like ? or address like ? or category like ?)'); params += ['%'+q+'%']*5
    if s in ALLOWED_STATUS: where.append('status=?'); params.append(s)
    if where: sql += ' where ' + ' and '.join(where)
    rows=c.execute(sql+' order by id desc',params).fetchall(); c.close(); return jsonify(leads=[dict(x) for x in rows])

@app.post('/api/scrape')
def start():
    d=request.json or {}; p=str(d.get('postcode','')).upper().strip(); a=int(d.get('amount',0) or 0)
    if not p or not 1 <= a <= MAX_LEADS: return jsonify(error=f'Amount must be 1-{MAX_LEADS}'),400
    if state['running']: return jsonify(error='A scrape is already running'),409
    threading.Thread(target=scrape,args=(p,a),daemon=True).start(); return jsonify(ok=True)

@app.post('/api/leads')
def create():
    d=request.json or {}; name=str(d.get('name','')).strip()
    if not name: return jsonify(error='Business name is required'),400
    s=d.get('status','new'); s=s if s in ALLOWED_STATUS else 'new'; c=db(); cur=c.execute('insert into leads(name,category,phone,email,address,website,status) values(?,?,?,?,?,?,?)',(name,d.get('category',''),d.get('phone',''),d.get('email',''),d.get('address',''),d.get('website',''),s)); c.commit(); c.close(); return jsonify(id=cur.lastrowid)

@app.patch('/api/leads/<int:i>')
def patch(i):
    d=request.json or {}; s=d.get('status','new')
    if s not in ALLOWED_STATUS:return jsonify(error='Invalid status'),400
    c=db();cur=c.execute('update leads set status=?,name=coalesce(?,name),phone=coalesce(?,phone),email=coalesce(?,email),address=coalesce(?,address),category=coalesce(?,category),website=coalesce(?,website) where id=?',(s,d.get('name'),d.get('phone'),d.get('email'),d.get('address'),d.get('category'),d.get('website'),i));c.commit();c.close();return jsonify(ok=cur.rowcount>0)

@app.delete('/api/leads/<int:i>')
def delete(i):
    c=db();c.execute('delete from leads where id=?',(i,));c.commit();c.close();return jsonify(ok=True)

@app.post('/api/leads/bulk-delete')
def bulk():
    ids=request.json.get('ids',[]);c=db();c.executemany('delete from leads where id=?',[(int(i),) for i in ids]);c.commit();c.close();return jsonify(ok=True)

@app.post('/api/leads/bulk-status')
def bulk_status():
    d=request.json or {};s=d.get('status');ids=d.get('ids',[])
    if s not in ALLOWED_STATUS:return jsonify(error='Invalid status'),400
    c=db();c.executemany('update leads set status=? where id=?',[(s,int(i)) for i in ids]);c.commit();c.close();return jsonify(ok=True)

@app.get('/api/export.csv')
def export():
    c=db();rows=c.execute('select * from leads order by id desc').fetchall();c.close();out=io.StringIO();w=csv.writer(out);w.writerow(rows[0].keys() if rows else ['id','name','category','phone','email','address','website','status','created_at']);w.writerows([tuple(r) for r in rows]);return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=leads.csv'})

if __name__=='__main__':db().close();app.run(host=HOST,port=PORT)
