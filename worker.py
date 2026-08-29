"""Dedicated persistent scrape worker for Pi 2/ARMv7.
The web server only queues jobs; this process owns scraping so Gunicorn restarts
or multiple web workers cannot interrupt or duplicate jobs.
"""
import os,time,threading
from main import db, log, DB_LOCK, CONTROL
from scraper.maps import search_google_maps

def run_job(jid,p,target):
    try:
        with DB_LOCK:
            c=db(); row=c.execute('select status from scrape_jobs where id=?',(jid,)).fetchone()
            if not row or row['status']=='deleted': c.close(); return
            c.execute('update scrape_jobs set status="running",started_at=?,error="" where id=?',(time.time(),jid));log(c,jid,f'Started {p}, target {target}');c.close()
        seen=set(); found=0; saved=0
        def on_result(r):
            nonlocal found,saved
            with DB_LOCK:
                c=db(); state=c.execute('select status from scrape_jobs where id=?',(jid,)).fetchone()
                if not state or state['status']=='deleted': c.close(); raise RuntimeError('JOB_DELETED')
                while state['status']=='paused':
                    c.close(); CONTROL.wait(timeout=2); c=db(); state=c.execute('select status from scrape_jobs where id=?',(jid,)).fetchone()
                    if not state or state['status']=='deleted': c.close(); raise RuntimeError('JOB_DELETED')
                found += 1
                name=str(r.get('name') or '').strip(); key=str(r.get('place_id') or name).strip().lower()
                if name and key not in seen and not r.get('website'):
                    seen.add(key)
                    c.execute('insert into leads(job_id,name,category,phone,email,address,website) values(?,?,?,?,?,?,?)',(jid,name,r.get('category',''),r.get('phone',''),r.get('email',''),r.get('address',''),r.get('website','')))
                    saved += 1
                c.execute('update scrape_jobs set found=?,saved=? where id=?',(found,saved,jid));c.commit();c.close()
        search_google_maps(p,target,on_result=on_result)
        with DB_LOCK:
            c=db();state=c.execute('select status from scrape_jobs where id=?',(jid,)).fetchone()
            if state and state['status']!='deleted':
                c.execute('update scrape_jobs set status="complete",found=?,saved=?,finished_at=? where id=?',(found,saved,time.time(),jid));log(c,jid,f'Finished: {saved} leads saved')
            c.close()
    except Exception as e:
        if str(e)=='JOB_DELETED': return
        with DB_LOCK:
            c=db();state=c.execute('select status from scrape_jobs where id=?',(jid,)).fetchone()
            if state and state['status']!='deleted':
                c.execute('update scrape_jobs set status="error",error=?,finished_at=? where id=?',(str(e),time.time(),jid));log(c,jid,'ERROR: '+str(e))
            c.close()

def main_loop():
    while True:
        with DB_LOCK:
            c=db()
            # A reboot leaves running jobs in the database; restart them. Paused jobs stay paused.
            c.execute('update scrape_jobs set status="queued",error="Resuming after worker restart" where status="running"')
            rows=c.execute('select id,postcode,target from scrape_jobs where status="queued" order by coalesce(started_at,0),rowid').fetchall()
            c.close()
        # One active job per worker keeps RAM/CPU bounded on Pi 2.
        if rows:
            r=rows[0]; run_job(r['id'],r['postcode'],r['target'])
        else:
            time.sleep(1)

if __name__=='__main__': main_loop()
