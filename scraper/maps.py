import json, os, re, urllib.parse, urllib.request
from config import REQUEST_TIMEOUT

BASE='https://maps.googleapis.com/maps/api/place'

def _get(path, params):
    params=dict(params);params['key']=os.getenv('GOOGLE_MAPS_API_KEY','')
    if not params['key']: raise RuntimeError('GOOGLE_MAPS_API_KEY is not configured')
    url=BASE+path+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'User-Agent':'py-scrape/1.0'})
    with urllib.request.urlopen(req,timeout=REQUEST_TIMEOUT) as r:return json.loads(r.read().decode())

def search_google_maps(postcode, amount):
    # Places Text Search is used instead of browser automation, keeping the Pi 2 workload small.
    query=f'businesses in {postcode}, London, UK'
    first=_get('/textsearch/json',{'query':query})
    results=list(first.get('results',[]))
    token=first.get('next_page_token')
    while len(results)<amount and token:
        import time;time.sleep(2)
        page=_get('/textsearch/json',{'pagetoken':token});results.extend(page.get('results',[]));token=page.get('next_page_token')
    out=[]
    for p in results[:amount]:
        d=_get('/details/json',{'place_id':p.get('place_id'),'fields':'name,formatted_address,formatted_phone_number,website,types,url'})
        x=d.get('result',{})
        out.append({'name':x.get('name',p.get('name','')),'category':(x.get('types') or [''])[0],'phone':x.get('formatted_phone_number',''),'email':'','address':x.get('formatted_address',p.get('formatted_address','')),'website':x.get('website',''),'maps_url':x.get('url','')})
    return out
