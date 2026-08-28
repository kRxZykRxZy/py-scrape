from flask import Flask,request,jsonify,send_from_directory,Response
import csv,io,sqlite3,threading,time,os
app=Flask(__name__,static_folder='web/static')
DB='data/py_scrape.db'; os.makedirs('data',exist_ok=True)
state={'running':False,'state':'idle','found':0,'saved':0,'logs':[]}
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('''create table if not exists leads(id integer primary key autoincrement,name text not null,category text,phone text,email text,address text,website text,status text default 'new',created_at text default current_timestamp)'''); c.commit(); return c
def log(x): state['logs'].append(time.strftime('%H:%M:%S ')+x); state['logs']=state['logs'][-200:]
def scrape(postcode,amount):
 state.update(running=True,state='scraping',found=0,saved=0,logs=[]); log(f'Started {postcode}, target {amount}')
 try:
  from scraper.maps import search_google_maps
  rows=search_google_maps(postcode,amount)
  c=db()
  for r in rows:
   state['found']+=1
   if r.get('website'): continue
   c.execute('insert into leads(name,category,phone,email,address,website) values(?,?,?,?,?,?)',(r.get('name',''),r.get('category',''),r.get('phone',''),r.get('email',''),r.get('address',''),r.get('website','')));state['saved']+=1
  c.commit();c.close();log(f'Finished: {state["saved"]} leads saved')
 except Exception as e: log('ERROR: '+str(e))
 finally: state['running']=False;state['state']='complete'
@app.get('/')
def index(): return send_from_directory('web','index.html')
@app.get('/static/<path:p>')
def static(p): return send_from_directory('web/static',p)
@app.get('/api/status')
def status():
 c=db();state['total']=c.execute('select count(*) from leads').fetchone()[0];c.close();return jsonify(state)
@app.get('/api/leads')
def leads():
 q=request.args.get('search','');c=db(); rows=c.execute('select * from leads where name like ? or phone like ? or email like ? order by id desc',('%'+q+'%',)*3).fetchall();c.close();return jsonify(leads=[dict(x) for x in rows])
@app.post('/api/scrape')
def start():
 d=request.json or {};p=str(d.get('postcode','')).upper().strip();a=int(d.get('amount',0));
 if not p or a<1:return jsonify(error='Invalid input'),400
 if state['running']:return jsonify(error='A scrape is already running'),409
 threading.Thread(target=scrape,args=(p,a),daemon=True).start();return jsonify(ok=True)
@app.post('/api/leads')
def create():
 d=request.json or {};c=db();cur=c.execute('insert into leads(name,category,phone,email,address,website,status) values(?,?,?,?,?,?,?)',(d.get('name',''),d.get('category',''),d.get('phone',''),d.get('email',''),d.get('address',''),d.get('website',''),d.get('status','new')));c.commit();c.close();return jsonify(id=cur.lastrowid)
@app.patch('/api/leads/<int:i>')
def patch(i):
 s=request.json.get('status','new');c=db();c.execute('update leads set status=? where id=?',(s,i));c.commit();c.close();return jsonify(ok=True)
@app.delete('/api/leads/<int:i>')
def delete(i):
 c=db();c.execute('delete from leads where id=?',(i,));c.commit();c.close();return jsonify(ok=True)
@app.post('/api/leads/bulk-delete')
def bulk():
 ids=request.json.get('ids',[]);c=db();c.executemany('delete from leads where id=?',[(int(i),) for i in ids]);c.commit();c.close();return jsonify(ok=True)
@app.get('/api/export.csv')
def export():
 c=db();rows=c.execute('select * from leads order by id desc').fetchall();c.close();out=io.StringIO();w=csv.writer(out);w.writerow(rows[0].keys() if rows else ['name','category','phone','email','address','website','status']);w.writerows([tuple(r) for r in rows]);return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=leads.csv'})
if __name__=='__main__': db().close();app.run(host='0.0.0.0',port=81)
