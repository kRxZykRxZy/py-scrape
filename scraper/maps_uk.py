"""UK-wide Google Places Text Search client for ARMv7/Pi 2.
Accepts any UK postcode district and rotates multiple API keys on API/network errors.
"""
import json, os, re, time, urllib.error, urllib.request
API_URL='https://places.googleapis.com/v1/places:searchText'
POSTCODES_URL='https://api.postcodes.io/outcodes/{}'
API_KEYS=[x.strip() for x in os.getenv('GOOGLE_MAPS_API_KEYS', os.getenv('GOOGLE_MAPS_API_KEY','')).split('|') if x.strip()]
TIMEOUT=float(os.getenv('MAPS_TIMEOUT','15')); PAGE_SIZE=20
POSTCODE_RE=re.compile(r'^[A-Z]{1,2}\d[A-Z\d]?$',re.I)
CATEGORIES=['accountants','estate agents','solicitors','dentists','plumbers','electricians','builders','cleaning services','hair salons','beauty salons','garages','gyms','photographers','florists','mechanics','roofers','landscapers','printing services','computer shops','auto repair','restaurants','cafes','contractors','shops','offices']
BLOCKED_TYPES={'premise','subpremise','apartment_building','apartment_complex','housing_complex','lodging','route','locality','political','park','school','church','mosque','cemetery','parking','bus_station','train_station'}
_key_index=0

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

def validate_postcode(postcode):
    value=re.sub(r'\s+','',_text(postcode)).upper()
    if not POSTCODE_RE.fullmatch(value):raise ValueError('Enter a UK postcode district such as UB10, NW10, M1, B1 or EH1')
    return value

def _area(outcode):
    data=_request(POSTCODES_URL.format(outcode));result=data.get('result') if isinstance(data,dict) else None
    if not isinstance(result,dict):raise ValueError('UK postcode district was not found')
    district=_text(result.get('admin_district','')).strip();b=result.get('bounds')
    if not isinstance(b,dict) or not all(k in b for k in ('north','south','east','west')):
        lat=float(result['latitude']);lon=float(result['longitude']);b={'north':lat+.01,'south':lat-.01,'east':lon+.015,'west':lon-.015}
    return b,district

def _rotate_key():
    global _key_index
    if API_KEYS:_key_index=(_key_index+1)%len(API_KEYS)

def _search(query,bounds,token=None):
    if not API_KEYS:raise RuntimeError('GOOGLE_MAPS_API_KEYS is not configured (use | between multiple keys)')
    body={'textQuery':query,'pageSize':PAGE_SIZE,'regionCode':'GB','locationRestriction':{'rectangle':{'low':{'latitude':bounds['south'],'longitude':bounds['west']},'high':{'latitude':bounds['north'],'longitude':bounds['east']}}}}
    if token:body['pageToken']=str(token)
    last=None
    for _ in range(len(API_KEYS)):
        key=API_KEYS[_key_index%len(API_KEYS)]
        headers={'Content-Type':'application/json','X-Goog-Api-Key':key,'X-Goog-FieldMask':'places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,places.types,places.businessStatus,nextPageToken','User-Agent':'py-scrape/1.0'}
        try:return _request(API_URL,body,headers,'POST')
        except RuntimeError as exc:
            last=exc;msg=str(exc)
            if any(x in msg for x in ('HTTP 400','HTTP 401','HTTP 403','HTTP 429','HTTP 500','HTTP 502','HTTP 503','HTTP 504','Network request failed')):
                _rotate_key();continue
            raise
    raise RuntimeError('All configured Google Maps API keys failed: %s'%last)

def _normalise(place,outcode,borough,category):
    place=place if isinstance(place,dict) else {};d=place.get('displayName');d=d if isinstance(d,dict) else {};types=place.get('types');types=types if isinstance(types,list) else [];types=[_text(x) for x in types]
    name=_text(d.get('text','')).strip();cat=(types[0].replace('_',' ').title() if types and types[0] else category.title())
    return {'place_id':_text(place.get('id','')),'name':name,'category':cat,'phone':_text(place.get('nationalPhoneNumber','')).strip(),'email':'','address':_text(place.get('formattedAddress','')).strip(),'website':'','maps_url':('https://www.google.com/maps/place/?q=place_id:'+_text(place.get('id','')) if place.get('id') else ''),'business_status':_text(place.get('businessStatus','')),'postcode_district':outcode,'borough':borough,'_types':types}

def _eligible(row):
    types={str(x).lower() for x in (row.get('_types') or [])};name=row.get('name','').lower()
    if types & BLOCKED_TYPES:return False
    if not row.get('name') or len(row['name'])<2:return False
    return not any(x in name for x in ('flat ','flat,','residence','residential block','car park','parking space'))

def search_google_maps(postcode,amount,on_result=None):
    from .enrich import enrich
    outcode=validate_postcode(postcode);bounds,borough=_area(outcode);target=max(1,min(int(amount),1000));results=[];seen=set()
    for category in CATEGORIES:
        if len(results)>=target:break
        token=None
        for _ in range(3):
            payload=_search('%s in %s, UK'%(category,outcode),bounds,token);places=payload.get('places',[]) if isinstance(payload,dict) else []
            if not isinstance(places,list):places=[]
            for place in places:
                if not isinstance(place,dict) or place.get('websiteUri'):continue
                row=_normalise(place,outcode,borough,category)
                if not _eligible(row):continue
                key=_text(row.get('place_id') or row.get('name','')).strip().lower()
                if not key or key in seen:continue
                seen.add(key);row=enrich(row);row.pop('_types',None)
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
