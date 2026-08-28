import os,sqlite3,time
from config import DB_PATH

def check():
    started=time.time(); os.makedirs(os.path.dirname(DB_PATH) or '.',exist_ok=True)
    c=sqlite3.connect(DB_PATH); c.execute('select 1'); c.close()
    return {'ok':True,'db':True,'latency_ms':round((time.time()-started)*1000,2)}
