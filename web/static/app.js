const $ = (s) => document.querySelector(s);

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function esc(value) {
  return String(value ?? '').replace(/[&<>\"]/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '\"':'&quot;' }[c]));
}

async function loadLeads() {
  const search = $('#filter')?.value || '';
  const status = $('#statusFilter')?.value || '';
  const data = await api(`/api/leads?search=${encodeURIComponent(search)}&status=${encodeURIComponent(status)}`);
  $('#leads').innerHTML = data.leads.map(l => `
    <tr>
      <td><input type="checkbox" class="lead" value="${Number(l.id)}"></td>
      <td>${esc(l.name)}</td><td>${esc(l.category)}</td><td>${esc(l.phone)}</td>
      <td>${esc(l.email)}</td><td>${esc(l.address)}</td>
      <td><select onchange="setStatus(${Number(l.id)},this.value)">${['new','contacted','qualified','won','lost'].map(s => `<option value="${s}" ${s === l.status ? 'selected' : ''}>${s}</option>`).join('')}</select></td>
      <td><button type="button" onclick="deleteLead(${Number(l.id)})">Delete</button></td>
    </tr>`).join('');
}

async function setStatus(id, status) {
  await api(`/api/leads/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) });
  loadLeads();
}

async function deleteLead(id) {
  if (!confirm('Delete this lead?')) return;
  await api(`/api/leads/${id}`, { method: 'DELETE' });
  loadLeads();
}

async function bulkDelete() {
  const ids = [...document.querySelectorAll('.lead:checked')].map(x => Number(x.value));
  if (!ids.length) return;
  if (!confirm(`Delete ${ids.length} selected leads?`)) return;
  await api('/api/leads/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) });
  loadLeads();
}

async function bulkStatus(status) {
  const ids = [...document.querySelectorAll('.lead:checked')].map(x => Number(x.value));
  if (!ids.length) return;
  await api('/api/leads/bulk-status', { method: 'POST', body: JSON.stringify({ ids, status }) });
  loadLeads();
}

async function createLead() {
  const data = Object.fromEntries(new FormData($('#create')).entries());
  try {
    await api('/api/leads', { method: 'POST', body: JSON.stringify(data) });
    $('#create').reset();
    loadLeads();
  } catch (error) { alert(error.message); }
}

async function refreshStatus() {
  try {
    const s = await api('/api/status');
    $('#stats').textContent = `Leads: ${s.total || 0} • ${s.running ? 'Scraping…' : 'Idle'}`;
    $('#progress').textContent = s.running ? `${s.state}: ${s.found || 0} found, ${s.saved || 0} saved` : '';
    $('#logs').textContent = (s.logs || []).join('\n');
    if (s.running) setTimeout(refreshStatus, 1000);
  } catch (_) {}
}

async function runScrape() {
  const postcode = $('#postcode').value.trim();
  const amount = Number($('#amount').value);
  if (!postcode || !Number.isInteger(amount) || amount < 1) return alert('Enter a valid postcode and lead count.');
  $('#run').disabled = true;
  try {
    await api('/api/scrape', { method: 'POST', body: JSON.stringify({ postcode, amount }) });
    refreshStatus();
    const wait = setInterval(async () => {
      const s = await api('/api/status');
      if (!s.running) { clearInterval(wait); $('#run').disabled = false; loadLeads(); refreshStatus(); }
    }, 1000);
  } catch (error) { $('#run').disabled = false; alert(error.message); }
}

document.addEventListener('DOMContentLoaded', () => {
  loadLeads();
  $('#run').addEventListener('click', runScrape);
  $('#bulkDelete').addEventListener('click', bulkDelete);
  $('#createBtn').addEventListener('click', createLead);
  $('#filter').addEventListener('input', loadLeads);
  refreshStatus();
});
