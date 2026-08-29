"""Lightweight Google Places Text Search client for ARMv7/Pi 2.
Returns only plausible commercial businesses that Google says have no website,
then performs conservative public-web enrichment before yielding each lead.
"""
import json, os, re, time, urllib.error, urllib.request
API_URL='https://places.googleapis.com/v1/places:searchText'; POSTCODES_URL='https://api.postcodes.io/outcodes/{}'
API_KEY=os.getenv('GOOGLE_MAPS_API_KEY','').strip(); TIMEOUT=float(os.getenv('MAPS_TIMEOUT','15')); PAGE_SIZE=20
POSTCODE_RE=re.compile(r'^[A-Z]{1,2}\d[A-Z\d]?$')
LONDON_PREFIXES={'BR','CR','DA','E','EC','EN','HA','IG','KT','N','NW','RM','SE','SM','SW','TW','UB','W','WC'}
LONDON_BOROUGHS={'Barking and Dagenham','Barnet','Bexley','Brent','Bromley','Camden','City of London','Croydon','Ealing','Enfield','Greenwich','Hackney','Hammersmith and Fulham','Haringey','Harrow','Havering','Hillingdon','Hounslow','Islington','Kensington and Chelsea','Kingston upon Thames','Lambeth','Lewisham','Merton','Newham','Redbridge','Richmond upon Thames','Southwark','Sutton','Tower Hamlets','Waltham Forest','Wandsworth','Westminster'}
# Specific commercial searches are much safer than a generic "businesses" query.
CATEGORIES=['accountants','estate agents','solicitors','dentists','plumbers','electricians','builders','cleaning services','hair salons','beauty salons','garages','gyms','photographers','florists','mechanics','roofers','landscapers','printing services','computer shops','auto repair','restaurants','cafes','contractors','shops','offices']
BLOCKED_TYPES={'premise','subpremise','apartment_building','apartment_complex','housing_complex','lodging','route','locality','political','park','school','church','mosque','cemetery','parking','bus_station','train_station'}

def _request(url,body=None,headers=None,method='GET'):
 data=None if body is None else json.dumps(body).encode();req=urllib.request.Request(url,data=data,headers=headers or {},method=method)
 try:
  with urllib.request.urlopen(req,timeout=TIMEOUT) as r:return json.loads(r.read().decode())
 except urllib.error.HTTPError as e:raise RuntimeError('HTTP %s: %s'%(e.code,e.read().decode('utf-8','replace')[:1000])) from e
 except urllib.error.URLError as e:raise RuntimeError('Network request failed: %s'%e.reason) from e

def _text(v):
 if isinstance(v,(list,tuple)):return ' '.join(_text(x) for x in v)
 if isinstance(v,dict):return ' '.join(_text(x) for x in v.values())
 return '' if v is None else str(v)

def _area(outcode):
 data=_request(POSTCODES_URL.format(outcode)); result=data.get('result') if isinstance(data,dict) else None
 if not isinstance(result,dict):raise ValueError('Postcode district was not found')
 district=_text(result.get('admin_district','')).strip()
 prefix_match=re.match(r'[A-Z]+',str(outcode)); prefix=prefix_match.group(0) if prefix_match else ''
 if prefix not in LONDON_PREFIXES or district not in LONDON_BOROUGHS:raise ValueError('Only London postcode districts are supported')
 b=result.get('bounds')
 if not isinstance(b,dict) or not all(k in b for k in ('north','south','east','west')):
  lat=float(result['latitude']);lon=float(result['longitude']);b={'north':lat+.01,'south':lat-.01,'east':lon+.015,'west':lon-.015}
 return b,district

def validate_postcode(postcode):
 value=re.sub(r'\s+','',_text(postcode)).upper()
 if not POSTCODE_RE.fullmatch(value):raise ValueError('Enter a London postcode district such as UB10 or NW10')
 return value

def _search(query,bounds,token=None):
 body={'textQuery':query,'pageSize':PAGE_SIZE,'regionCode':'GB','locationRestriction':{'rectangle':{'low':{'latitude':bounds['south'],'longitude':bounds['west']},'high':{'latitude':bounds['north'],'longitude':bounds['east']}}}}
 if token:body['pageToken']=str(token)
 headers={'Content-Type':'application/json','X-Goog-Api-Key':API_KEY,'X-Goog-FieldMask':'places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,places.types,places.businessStatus,nextPageToken','User-Agent':'py-scrape/1.0'}
 return _request(API_URL,body,headers,'POST')

def _normalise(place,outcode,borough,category):
 place=place if isinstance(place,dict) else {}; d=place.get('displayName');d=d if isinstance(d,dict) else {}
 types=place.get('types');types=types if isinstance(types,list) else [];types=[_text(x) for x in types]
 name=_text(d.get('text','')).strip(); cat=(types[0].replace('_',' ').title() if types and types[0] else category.title())
 return {'place_id':_text(place.get('id','')),'name':name,'category':cat,'phone':_text(place.get('nationalPhoneNumber','')).strip(),'email':'','address':_text(place.get('formattedAddress','')).strip(),'website':'','maps_url':'','business_status':_text(place.get('businessStatus','')),'postcode_district':outcode,'borough':borough,'_types':types}

def _eligible(row):
 types={str(x).lower() for x in (row.get('_types') or [])}
 name=row.get('name','').lower()
 if types & BLOCKED_TYPES:return False
 if not row.get('name') or len(row['name'])<2:return False
 # Reject obvious non-commercial map labels that sometimes leak through broad searches.
 if any(x in name for x in ('flat ','flat,','residence','residential block','car park','parking space')):return False
 return True

def search_google_maps(postcode,amount,on_result=None):
 if not API_KEY:raise RuntimeError('GOOGLE_MAPS_API_KEY is not configured')
 from .enrich import enrich
 outcode=validate_postcode(postcode);bounds,borough=_area(outcode);target=max(1,min(int(amount),1000));results=[];seen=set()
 for category in CATEGORIES:
  if len(results)>=target:break
  token=None
  for _ in range(3):
   payload=_search('%s in %s, London, UK'%(category,outcode),bounds,token); places=payload.get('places',[]) if isinstance(payload,dict) else []
   if not isinstance(places,list):places=[]
   for place in places:
    if not isinstance(place,dict) or place.get('websiteUri'):continue
    row=_normalise(place,outcode,borough,category)
    if not _eligible(row):continue
    key=_text(row.get('place_id') or row.get('name','')).strip().lower()
    if not key or key in seen:continue
    seen.add(key)
    # Public-web enrichment is best-effort. If it finds a real business website,
    # this is no longer a "no website" lead and is excluded from the final set.
    row=enrich(row)
    row.pop('_types',None)
    if row.get('website'):continue
    results.append(row)
    if on_result:
     try:on_result(row)
     except Exception:pass
    if len(results)>=target:break
   if len(results)>=target:break
   token=payload.get('nextPageToken') if isinstance(payload,dict) else None
   if not token:break
   time.sleep(1.2)
 return results[:target]
