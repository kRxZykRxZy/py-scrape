"""Dedicated persistent scrape worker for Pi 2/ARMv7.
Runs up to three independent scrape jobs concurrently using Python threads.
The Maps scraper API is intentionally unchanged; concurrency is provided here.
"""
import time, threading
from main import db, log, DB_LOCK, CONTROL
from scraper.maps import search_google_maps
MAX_THREADS = 3

def run_job(jid, postcode, target):
    try:
        with DB_LOCK:
            c = db(); row = c.execute('select status from scrape_jobs where id=?', (jid,)).fetchone()
            if not row or row['status'] == 'deleted': c.close(); return
            c.execute('update scrape_jobs set status="running",started_at=?,error="" where id=?', (time.time(), jid))
            log(c, jid, f'Started {postcode}, target {target} (thread {threading.current_thread().name})'); c.close()
        seen = set(); found = saved = 0
        def on_result(r):
            nonlocal found, saved
            with DB_LOCK:
                c = db(); state = c.execute('select status from scrape_jobs where id=?', (jid,)).fetchone()
                if not state or state['status'] == 'deleted': c.close(); raise RuntimeError('JOB_DELETED')
                while state['status'] == 'paused':
                    c.close(); CONTROL.wait(timeout=2); c = db(); state = c.execute('select status from scrape_jobs where id=?', (jid,)).fetchone()
                    if not state or state['status'] == 'deleted': c.close(); raise RuntimeError('JOB_DELETED')
                found += 1
                name = str(r.get('name') or '').strip(); key = str(r.get('place_id') or name).strip().lower()
                if name and key not in seen and not r.get('website'):
                    seen.add(key)
                    c.execute('insert into leads(job_id,name,category,phone,email,address,website) values(?,?,?,?,?,?,?)', (jid,name,r.get('category',''),r.get('phone',''),r.get('email',''),r.get('address',''),r.get('website','')))
                    saved += 1
                c.execute('update scrape_jobs set found=?,saved=? where id=?', (found,saved,jid)); c.commit(); c.close()
        # IMPORTANT: maps.py does not accept a threads= parameter. The three
        # worker threads call the stable scraper API independently.
        search_google_maps(postcode, target, on_result=on_result)
        with DB_LOCK:
            c = db(); state = c.execute('select status from scrape_jobs where id=?', (jid,)).fetchone()
            if state and state['status'] != 'deleted':
                c.execute('update scrape_jobs set status="complete",found=?,saved=?,finished_at=? where id=?', (found,saved,time.time(),jid)); log(c,jid,f'Finished: {saved} leads saved')
            c.close()
    except Exception as e:
        if str(e) == 'JOB_DELETED': return
        with DB_LOCK:
            c = db(); state = c.execute('select status from scrape_jobs where id=?', (jid,)).fetchone()
            if state and state['status'] != 'deleted':
                c.execute('update scrape_jobs set status="error",error=?,finished_at=? where id=?', (str(e),time.time(),jid)); log(c,jid,'ERROR: '+str(e))
            c.close()

def main_loop():
    active = {}
    while True:
        with DB_LOCK:
            c = db(); c.execute('update scrape_jobs set status="queued",error="Resuming after worker restart" where status="running"'); c.commit()
            rows = c.execute('select id,postcode,target from scrape_jobs where status="queued" order by coalesce(started_at,0),rowid').fetchall(); c.close()
        for jid, t in list(active.items()):
            if not t.is_alive(): active.pop(jid, None)
        for r in rows:
            if len(active) >= MAX_THREADS or r['id'] in active: break
            t = threading.Thread(target=run_job, args=(r['id'],r['postcode'],r['target']), name=f'scrape-{r["id"]}', daemon=True)
            active[r['id']] = t; t.start()
        time.sleep(0.5)

if __name__ == '__main__': main_loop()
