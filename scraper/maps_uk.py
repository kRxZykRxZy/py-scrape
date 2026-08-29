"""UK-wide business discovery with provider failover."""
import os,re,json,urllib.request,urllib.parse
from .providers import google,foursquare,yelp,osm,KEYS
POSTCODES_URL='https://api.postcodes.io/outcodes/{}'; TIMEOUT=float(os.getenv('MAPS_TIMEOUT','15'))
POSTCODE_RE=re.compile(r'^[A-Z]{1,2}\d[A-Z\d]?$',re.I)
CATEGORIES=['accountants','estate agents','solicitors','dentists','plumbers','electricians','builders','cleaning services','hair salons','beauty salons','garages','gyms','photographers','florists','mechanics','roofers','landscapers','printing services','computer shops','auto repair','restaurants','cafes','contractors','shops','offices']
BLOCKED={'premise','subpremise','apartment_building','apartment_complex','housing_complex','lodging','route','locality','political','park','school','church','mosque','cemetery','parking','bus_station','train_station'}
ORDER=[x.strip().lower() for x in os.getenv('SEARCH_PROVIDER_ORDER','google,foursquare,yelp,osm').split(',') if x.strip()]
def _req(url):
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'py-scrape/1.0'}),timeout=TIMEOUT) as r:return json.loads(r.read().decode())
def _txt(v):
 if isinstance(v,(list,tuple)):return ' '.join(_txt(x) for x in v)
 if isinstance(v,dict):return ' '.join(_txt(x) for x in v.values())
 return '' if v is None else str(v)
def validate_postcode(p):
 p=re.sub(r'\s+','',_txt(p)).upper()
 if not POSTCODE_RE.fullmatch(p):raise ValueError('Enter a UK postcode district such as UB10, M1, B1 or EH1')
 return p
def _area(p):
 r=_req(POSTCODES_URL.format(urllib.parse.quote(p))).get('result')
 if not isinstance(r,dict):raise ValueError('UK postcode district was not found')
 b=r.get('bounds')
 if not isinstance(b,dict) or not all(k in b for k in ('north','south','east','west')):
  lat=float(r['latitude']);lon=float(r['longitude']);b={'north':lat+.01,'south':lat-.01,'east':lon+.015,'west':lon-.015}
 return b,_txt(r.get('admin_district','')).strip()
def _norm(provider,p,out,borough,cat):
 if provider=='google':
  d=p.get('displayName') or {};t=p.get('types') or [];return {'place_id':_txt(p.get('id')),'name':_txt(d.get('text')).strip(),'category':(_txt(t[0]).replace('_',' ').title() if t else cat.title()),'phone':_txt(p.get('nationalPhoneNumber')).strip(),'email':'','address':_txt(p.get('formattedAddress')).strip(),'website':_txt(p.get('websiteUri')).strip(),'maps_url':'https://www.google.com/maps/place/?q=place_id:'+_txt(p.get('id')) if p.get('id') else '','business_status':_txt(p.get('businessStatus')),'_types':t}
 if provider=='foursquare':
  l=p.get('location') or {};c=p.get('categories') or [];return {'place_id':_txt(p.get('fsq_id')),'name':_txt(p.get('name')).strip(),'category':_txt(c[0].get('name')) if c else cat.title(),'phone':_txt(p.get('tel')).strip(),'email':'','address':_txt(l.get('formatted_address') or l.get('address')).strip(),'website':_txt(p.get('website')).strip(),'maps_url':'https://foursquare.com/place/'+_txt(p.get('fsq_id')) if p.get('fsq_id') else '','business_status':'','_types':[]}
 if provider=='yelp':
  l=p.get('location') or {};c=p.get('categories') or [];return {'place_id':_txt(p.get('id')),'name':_txt(p.get('name')).strip(),'category':_txt(c[0].get('title')) if c else cat.title(),'phone':_txt(p.get('display_phone') or p.get('phone')).strip(),'email':'','address':', '.join(l.get('display_address') or []),'website':'','maps_url':_txt(p.get('url')),'business_status':'','_types':[]}
 t=p.get('tags') or {};ce=p.get('center') or {};lat=p.get('lat',ce.get('lat'));lon=p.get('lon',ce.get('lon'));return {'place_id':'osm:'+_txt(p.get('type'))+':'+_txt(p.get('id')),'name':_txt(t.get('name')).strip(),'category':_txt(t.get('shop') or t.get('amenity') or t.get('craft') or cat).replace('_',' ').title(),'phone':_txt(t.get('phone') or t.get('contact:phone')),'email':_txt(t.get('email') or t.get('contact:email')),'address':', '.join(_txt(t.get(k)) for k in ('addr:housenumber','addr:street','addr:postcode') if t.get(k)),'website':_txt(t.get('website') or t.get('contact:website')),'maps_url':('https://www.openstreetmap.org/?mlat=%s&mlon=%s'%(lat,lon) if lat is not None and lon is not None else ''),'business_status':'','_types':[]}
def _eligible(r):
 t={str(x).lower() for x in r.get('_types',[])};n=r.get('name','').lower();return bool(r.get('name')) and not t.intersection(BLOCKED) and not any(x in n for x in ('flat ','flat,','residential block','car park','parking space'))
def search_google_maps(postcode,amount,on_result=None):
 from .enrich import enrich
 out=validate_postcode(postcode);b,borough=_area(out);target=max(1,min(int(amount),1000));results=[];seen=set()
 providers=[p for p in ORDER if p=='osm' or KEYS.get(p)]
 if not providers:raise RuntimeError('Configure GOOGLE_MAPS_API_KEY(S), FOURSQUARE_API_KEY(S), or YELP_API_KEY(S), or enable osm')
 for provider in providers:
  if len(results)>=target:break
  failed=False
  for cat in CATEGORIES:
   if len(results)>=target:break
   try:
    if provider=='google':raw=google('%s in %s, UK'%(cat,out),b).get('places',[])
    elif provider=='foursquare':raw=foursquare(cat,b).get('results',[])
    elif provider=='yelp':raw=yelp(cat,b).get('businesses',[])
    else:raw=osm(cat,b).get('elements',[])
   except Exception:failed=True;break
   for p in raw if isinstance(raw,list) else []:
    r=_norm(provider,p,out,borough,cat)
    if not _eligible(r):continue
    k=_txt(r.get('place_id') or r.get('name')).strip().lower()
    if not k or k in seen:continue
    seen.add(k)
    try:r=enrich(r)
    except Exception:pass
    if r.get('website'):continue
    r.pop('_types',None);r['source_provider']=provider;results.append(r)
    if on_result:
     try:on_result(r)
     except Exception:pass
    if len(results)>=target:break
  if failed:continue
 return results[:target]
