import os,json,urllib.parse,urllib.request,urllib.error
TIMEOUT=float(os.getenv('MAPS_TIMEOUT','15'))

def keys(*names):
 for n in names:
  v=os.getenv(n,'').strip()
  if v:return [x.strip() for x in v.split('|') if x.strip()]
 return []
KEYS={'google':keys('GOOGLE_MAPS_API_KEYS','GOOGLE_MAPS_API_KEY'),'foursquare':keys('FOURSQUARE_API_KEYS','FOURSQUARE_API_KEY'),'yelp':keys('YELP_API_KEYS','YELP_API_KEY')}
POS={'google':0,'foursquare':0,'yelp':0}
OVERPASS=[x.strip() for x in os.getenv('OVERPASS_URLS','https://overpass-api.de/api/interpreter|https://overpass.kumi.systems/api/interpreter').split('|') if x.strip()]

def req(url,body=None,headers=None,method='GET'):
 d=body if isinstance(body,bytes) else (json.dumps(body).encode() if body is not None else None)
 try:
  with urllib.request.urlopen(urllib.request.Request(url,data=d,headers=headers or {},method=method),timeout=TIMEOUT) as r:return json.loads(r.read().decode('utf8','replace'))
 except urllib.error.HTTPError as e:raise RuntimeError('HTTP %s: %s'%(e.code,e.read().decode('utf8','replace')[:500]))
 except urllib.error.URLError as e:raise RuntimeError('Network request failed: %s'%e.reason)

def retryable(e):return any(x in str(e) for x in ('HTTP 400','HTTP 401','HTTP 403','HTTP 408','HTTP 429','HTTP 500','HTTP 502','HTTP 503','HTTP 504','Network request failed'))

def with_keys(p,fn):
 ks=KEYS[p]
 if not ks:raise RuntimeError('%s API key not configured'%p)
 last=None
 for _ in range(len(ks)):
  try:return fn(ks[POS[p]%len(ks)])
  except RuntimeError as e:
   last=e
   if not retryable(e):raise
   POS[p]=(POS[p]+1)%len(ks)
 raise RuntimeError('All %s API keys failed: %s'%(p,last))

def google(q,b,token=None):
 body={'textQuery':q,'pageSize':20,'regionCode':'GB','locationRestriction':{'rectangle':{'low':{'latitude':b['south'],'longitude':b['west']},'high':{'latitude':b['north'],'longitude':b['east']}}}}
 if token:body['pageToken']=token
 def f(k):return req('https://places.googleapis.com/v1/places:searchText',body,{'Content-Type':'application/json','X-Goog-Api-Key':k,'X-Goog-FieldMask':'places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,places.types,places.businessStatus,nextPageToken','User-Agent':'py-scrape/1.0'},'POST')
 return with_keys('google',f)

def foursquare(q,b):
 p={'query':q,'ne':'%s,%s'%(b['north'],b['east']),'sw':'%s,%s'%(b['south'],b['west']),'limit':50,'fields':'fsq_id,name,location,tel,website,categories'}
 u='https://places-api.foursquare.com/places/search?'+urllib.parse.urlencode(p)
 return with_keys('foursquare',lambda k:req(u,headers={'Accept':'application/json','Authorization':'Bearer '+k,'X-Places-Api-Version':'2025-06-17'}))

def yelp(q,b,offset=0):
 lat=(b['north']+b['south'])/2;lon=(b['east']+b['west'])/2
 radius=min(40000,max(1000,int(111000*min((b['north']-b['south'])/2,(b['east']-b['west'])/2)*.95)))
 p={'term':q,'latitude':lat,'longitude':lon,'radius':radius,'limit':50,'offset':offset,'locale':'en_GB'}
 u='https://api.yelp.com/v3/businesses/search?'+urllib.parse.urlencode(p)
 return with_keys('yelp',lambda k:req(u,headers={'Authorization':'Bearer '+k,'Accept':'application/json'}))

def osm(q,b):
 query='[out:json][timeout:25];nwr["name"](%s,%s,%s,%s);out center tags;'%(b['south'],b['west'],b['north'],b['east'])
 last=None
 for u in OVERPASS:
  try:return req(u,query.encode(),{'Content-Type':'text/plain','User-Agent':'py-scrape/1.0'},'POST')
  except RuntimeError as e:
   last=e
 raise RuntimeError('All Overpass endpoints failed: %s'%last)
