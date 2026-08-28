// Phase 5 lead operations.
async function p5Api(url,options={}){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...options});if(!r.ok)throw new Error(await r.text());return r.json()}
async function bulkStatus(status){const ids=[...document.querySelectorAll('.lead:checked')].map(x=>+x.value);if(!ids.length)return;await p5Api('/api/leads/bulk-status',{method:'POST',body:JSON.stringify({ids,status})});loadLeads()}
async function refreshStats(){try{const s=await p5Api('/api/status');const el=document.querySelector('#stats');if(el)el.textContent=`Leads: ${s.total||0} • Running: ${s.running?'yes':'no'} • Saved: ${s.saved||0}`}catch(_){} }
setInterval(refreshStats,2000);