from flask import Flask,request,jsonify,send_from_directory,Response
import csv,io,sqlite3,threading,time,os,re
app=Flask(__name__,static_folder='web/static'); DB='data/py_scrape.db'; os.makedirs('data',exist_ok=True)
VALID_STATUSES={'new','contacted','qualified','won','lost'}
state={'running':False,'state':'idle','found':0,'saved':0,'logs':[]}
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
 c.execute('''create table if not exists leads(id integer primary key autoincrement,name text not null,category text,phone text,email text,address text,website text,status text default 'new',created_at text default current_timestamp)'''); c.commit(); return c
def log(x): state['logs'].append(time.strftime('%H:%M:%S ')+x); state['logs']=state['logs'][-200:]
def scrape(postcode,amount):
 state.update(running=True,state='scraping',found=0,saved=0,logs=[]); log(f'Started {postcode}, target {amount}')
 try:
  from scraper.maps import search_google_maps
  rows=search_google_maps(postcode,amount); c=db()
  for r in rows:
   state['found']+=1
   if r.get('website'): continue
   name=r.get('name','').strip(); phone=r.get('phone','').strip()
   exists=c.execute('select 1 from leads where lower(name)=lower(?) and (phone=? or phone is null or phone="")',(name,phone)).fetchone()
   if exists: continue
   c.execute('insert into leads(name,category,phone,email,address,website) values(?,?,?,?,?,?)',(name,r.get('category',''),phone,r.get('email',''),r.get('address',''),r.get('website',''))); state['saved']+=1
  c.commit(); c.close(); log(f'Finished: {state["saved"]} new leads saved')
 except Exception as e: log('ERROR: '+str(e))
 finally: state['running']=False; state['state']='complete'
@app.get('/')
def index(): return send_from_directory('web','index.html')
@app.get('/static/<path:p>')
def static(p): return send_from_directory('web/static',p)
@app.get('/api/status')
def status():
 c=db(); state['total']=c.execute('select count(*) from leads').fetchone()[0]; state['new']=c.execute("select count(*) from leads where status='new'").fetchone()[0]; state['contacted']=c.execute("select count(*) from leads where status='contacted'").fetchone()[0]; state['qualified']=c.execute("select count(*) from leads where status='qualified'").fetchone()[0]; state['won']=c.execute("select count(*) from leads where status='won'").fetchone()[0]; state['lost']=c.execute("select count(*) from leads where status='lost'").fetchone()[0]; c.close(); return jsonify(state)
@app.get('/api/leads')
def leads():
 q=request.args.get('search','').strip(); status=request.args.get('status',''); limit=min(max(int(request.args.get('limit',500)),1),1000); offset=max(int(request.args.get('offset',0)),0); c=db(); where=[]; args=[]
 if q: where.append('(name like ? or phone like ? or email like ? or address like ? or category like ?)'); args += ['%'+q+'%']*5
 if status in VALID_STATUSES: where.append('status=?'); args.append(status)
 sql='select * from leads'+((' where '+' and '.join(where)) if where else '')+' order by id desc limit ? offset ?'; args += [limit,offset]; rows=c.execute(sql,args).fetchall(); c.close(); return jsonify(leads=[dict(x) for x in rows],offset=offset,limit=limit)
@app.post('/api/scrape')
def start():
 d=request.json or {}; p=str(d.get('postcode','')).upper().strip(); a=int(d.get('amount',0));
 if not re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?',p) or a<1 or a>1000:return jsonify(error='Use a London postcode district such as UB10 or NW10 and an amount from 1-1000'),400
 if state['running']:return jsonify(error='A scrape is already running'),409
 threading.Thread(target=scrape,args=(p,a),daemon=True).start(); return jsonify(ok=True)
@app.post('/api/leads')
def create():
 d=request.json or {}; name=str(d.get('name','')).strip()
 if not name:return jsonify(error='Business name is required'),400
 s=d.get('status','new'); s=s if s in VALID_STATUSES else 'new'; c=db(); cur=c.execute('insert into leads(name,category,phone,email,address,website,status) values(?,?,?,?,?,?,?)',(name,d.get('category',''),d.get('phone',''),d.get('email',''),d.get('address',''),d.get('website',''),s)); c.commit(); c.close(); return jsonify(id=cur.lastrowid)
@app.patch('/api/leads/<int:i>')
def patch(i):
 d=request.json or {}; s=d.get('status'); c=db()
 if s is not None:
  if s not in VALID_STATUSES:return jsonify(error='Invalid status'),400
  c.execute('update leads set status=? where id=?',(s,i))
 else:
  fields=['name','category','phone','email','address','website']; vals=[d.get(x) for x in fields if x in d]
  if vals:
   names=[x for x in fields if x in d]; c.execute('update leads set '+','.join(x+'=?' for x in names)+' where id=?',vals+[i])
 c.commit(); c.close(); return jsonify(ok=True)
@app.delete('/api/leads/<int:i>')
def delete(i):
 c=db(); c.execute('delete from leads where id=?',(i,)); c.commit(); c.close(); return jsonify(ok=True)
@app.post('/api/leads/bulk-delete')
def bulk():
 ids=request.json.get('ids',[]); c=db(); c.executemany('delete from leads where id=?',[(int(i),) for i in ids]); c.commit(); c.close(); return jsonify(ok=True)
@app.post('/api/leads/bulk-status')
def bulk_status():
 d=request.json or {}; s=d.get('status'); ids=d.get('ids',[])
 if s not in VALID_STATUSES:return jsonify(error='Invalid status'),400
 c=db(); c.executemany('update leads set status=? where id=?',[(s,int(i)) for i in ids]); c.commit(); c.close(); return jsonify(ok=True,count=len(ids))
@app.get('/api/export.csv')
def export():
 c=db(); rows=c.execute('select * from leads order by id desc').fetchall(); c.close(); out=io.StringIO(); w=csv.writer(out); w.writerow(rows[0].keys() if rows else ['name','category','phone','email','address','website','status','created_at']); w.writerows([tuple(r) for r in rows]); return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=leads.csv'})
if __name__=='__main__': db().close(); app.run(host='0.0.0.0',port=81)
