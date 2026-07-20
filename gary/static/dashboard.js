const money = n => '$' + Number(n || 0).toLocaleString(undefined, {maximumFractionDigits: 0});
const GRID = 'rgba(255,255,255,0.06)';
const PALETTE = ['#3b82f6','#22c55e','#facc15','#f87171','#8b5cf6','#0ea5e9','#fb923c','#14b8a6','#ec4899'];
window._charts = window._charts || {};

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function escAttr(s) { return esc(s).replace(/'/g, '&#39;'); }
function safeUrl(url) {
  const u = String(url ?? '');
  return u.startsWith('https://') || u.startsWith('http://') ? u : '#';
}
function apiDetail(data, fallback) {
  if (Array.isArray(data.detail)) return data.detail.map(e => e.msg || JSON.stringify(e)).join('; ');
  if (typeof data.detail === 'string') return data.detail;
  return fallback;
}

function chart(id, config) {
  const el = document.getElementById(id);
  if (!el || typeof Chart === 'undefined') return;
  if (window._charts[id]) window._charts[id].destroy();
  Chart.defaults.color = '#8b98a5';
  Chart.defaults.font.family = 'Inter, system-ui, sans-serif';
  window._charts[id] = new Chart(el, config);
}

function setTopic(text) {
  const el = document.getElementById('topic');
  if (el) { el.value = text; el.focus(); }
  showTab('content');
}

function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
  location.hash = name;
}

function showAlert(id, msg, kind = 'error') {
  const el = document.getElementById(id);
  if (!el) return;
  if (!msg) { el.style.display = 'none'; el.textContent = ''; return; }
  el.className = 'alert alert-' + kind;
  el.textContent = msg;
  el.style.display = 'block';
}

async function withLoading(btn, fn) {
  if (!btn || btn.disabled) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Working…';
  try { return await fn(); }
  finally { btn.disabled = false; btn.innerHTML = orig; }
}

async function apiFetch(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(apiDetail(data, res.statusText || 'request failed'));
  return data;
}

// ---------- Tabs ----------
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => showTab(tab.dataset.tab));
});
const initialTab = (location.hash || '#overview').replace('#', '') || 'overview';
showTab(['overview','finances','property','content'].includes(initialTab) ? initialTab : 'overview');

// ---------- Content platform ----------
async function generate() {
  const topic = document.getElementById('topic').value.trim();
  if (!topic) { showAlert('content_alert', 'Enter a finance topic first.', 'error'); return; }
  showAlert('content_alert', '');
  try {
    const data = await apiFetch('/api/transcript', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic })
    });
    renderTranscriptResult(data);
    loadTranscripts();
  } catch (e) { showAlert('content_alert', e.message, 'error'); }
}

async function runPipeline() {
  const topic = document.getElementById('topic').value.trim();
  showAlert('content_alert', '');
  try {
    const data = await apiFetch('/api/pipeline/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(topic ? { topic } : {})
    });
    renderPipelineResult(data);
    loadVideos();
    loadTranscripts();
  } catch (e) { showAlert('content_alert', e.message, 'error'); }
}

function previewVideo() {
  const topic = document.getElementById('topic').value.trim() || 'Bitcoin ETF inflows';
  const v = document.getElementById('preview');
  v.style.display = 'block';
  v.src = '/api/story.mp4?topic=' + encodeURIComponent(topic) + '&t=' + Date.now();
  v.load(); v.play().catch(() => {});
}

function renderTranscriptResult(data) {
  const box = document.getElementById('content_result');
  box.style.display = 'block';
  document.getElementById('result_title').textContent = data.title;
  document.getElementById('result_thumb').src = '/api/thumbnail.svg?topic=' + encodeURIComponent(data.topic || data.title) + '&t=' + Date.now();
  document.getElementById('result_body').innerHTML =
    data.sections.map(s => `<p><strong>${esc(s.heading)}</strong><br>${esc(s.script)}</p>`).join('');
  document.getElementById('result_metrics').innerHTML = '';
}

function renderPipelineResult(data) {
  const box = document.getElementById('content_result');
  box.style.display = 'block';
  document.getElementById('result_title').textContent = data.transcript.title;
  document.getElementById('result_thumb').src = '/api/thumbnail.svg?topic=' + encodeURIComponent(data.topic) + '&t=' + Date.now();
  const m = data.metrics;
  document.getElementById('result_body').innerHTML =
    `<p class="muted">Topic: ${esc(data.topic)}</p>` +
    `<p>Long: ${data.video_long.total_seconds}s · ${data.video_long.segments.length} segments<br>` +
    `Short: ${data.video_short.total_seconds}s<br>` +
    `Thumbnail: ${esc(data.thumbnail.badge)} / ${esc(data.thumbnail.headline)}</p>` +
    `<p><a href="${escAttr(safeUrl(data.published.url))}" target="_blank" rel="noopener">Published → ${esc(data.published.url)}</a></p>`;
  document.getElementById('result_metrics').innerHTML =
    `<div class="metric"><div class="k">Views</div><div class="v">${m.views.toLocaleString()}</div></div>` +
    `<div class="metric"><div class="k">Likes</div><div class="v">${m.likes.toLocaleString()}</div></div>` +
    `<div class="metric"><div class="k">Comments</div><div class="v">${m.comments.toLocaleString()}</div></div>` +
    `<div class="metric"><div class="k">CTR</div><div class="v">${m.ctr_percent}%</div></div>`;
}

async function useTopTrend(market) {
  try {
    const data = await apiFetch('/api/trends?market=' + market + '&limit=1');
    if (!data.trends.length) return;
    const t = data.trends[0];
    setTopic(`${t.name} (${t.note || t.symbol})`);
  } catch (e) { showAlert('content_alert', e.message, 'error'); }
}

async function loadTrends(market, elId) {
  try {
    const data = await apiFetch('/api/trends?market=' + market);
    document.getElementById(elId).innerHTML = data.trends
      .map(t => {
        const topic = `${t.name} (${t.note || t.symbol})`;
        return `<li class="clickable" onclick="setTopic(${JSON.stringify(topic)})">` +
          `${esc(t.symbol)} <span class="muted">${esc(t.name)} · ${esc(t.note || t.score)}</span></li>`;
      }).join('');
  } catch (_) {
    document.getElementById(elId).innerHTML = '<li class="muted">Could not load trends.</li>';
  }
}

async function loadYouTube() {
  try {
    const data = await apiFetch('/api/youtube-trends');
    document.getElementById('youtube').innerHTML = data.topics
      .map(t => `<li class="clickable" onclick="setTopic(${JSON.stringify(t.title)})">` +
        `${esc(t.title)} <span class="muted">${esc(t.channel)} · ${t.views.toLocaleString()} views</span></li>`).join('');
  } catch (_) {
    document.getElementById('youtube').innerHTML = '<li class="muted">Could not load YouTube topics.</li>';
  }
}

async function loadVideos() {
  try {
    const data = await apiFetch('/api/videos');
    const el = document.getElementById('videos');
    if (!data.count) {
      el.innerHTML = '<li class="muted">Run the pipeline to publish a video.</li>';
      return;
    }
    el.innerHTML = data.videos.map(v => {
      const m = v.metrics;
      const date = (v.published_at || '').slice(0, 10);
      const vid = escAttr(v.video_id);
      return `<div class="video-card" id="video-${vid}">` +
        `<div class="title"><a href="${escAttr(safeUrl(v.url))}" target="_blank" rel="noopener">${esc(v.title)}</a></div>` +
        `<span class="muted">${esc(v.kind)} · ${esc(date)}</span> · ` +
        `${m.views.toLocaleString()} views · ${m.likes} likes · ${m.comments} comments · CTR ${m.ctr_percent}%` +
        `<div class="row" style="margin-top:8px;">` +
        `<button class="btn-slate" style="font-size:12px;padding:6px 10px;" onclick="toggleComments('${vid}')">Draft replies</button>` +
        `</div>` +
        `<div class="comment-box" id="comments-${vid}">` +
        `<textarea id="comment-input-${vid}" placeholder="One comment per line…"></textarea>` +
        `<button class="btn-slate" style="margin-top:6px;font-size:12px;padding:6px 10px;" onclick="draftReplies('${vid}')">Generate replies</button>` +
        `<div id="comment-replies-${vid}"></div></div></div>`;
    }).join('');
  } catch (e) {
    document.getElementById('videos').innerHTML = `<div class="muted">Could not load videos: ${esc(e.message)}</div>`;
  }
}

async function toggleComments(videoId) {
  const box = document.getElementById('comments-' + videoId);
  box.classList.toggle('open');
}

async function draftReplies(videoId) {
  const raw = document.getElementById('comment-input-' + videoId).value;
  const comments = raw.split('\n').map(s => s.trim()).filter(Boolean);
  if (!comments.length) return;
  try {
    const data = await apiFetch('/api/videos/' + videoId + '/comments', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comments })
    });
    document.getElementById('comment-replies-' + videoId).innerHTML = data.replies
      .map(r => `<div class="reply-item"><strong>Q:</strong> ${esc(r.comment)}<br><strong>A:</strong> ${esc(r.reply)}</div>`).join('');
  } catch (e) {
    document.getElementById('comment-replies-' + videoId).innerHTML =
      `<div class="alert alert-error">${esc(e.message)}</div>`;
  }
}

async function loadTranscripts() {
  try {
    const data = await apiFetch('/api/transcripts');
    const el = document.getElementById('transcripts');
    if (!data.count) {
      el.innerHTML = '<li class="muted">No transcripts yet. Generate one above.</li>';
      return;
    }
    el.innerHTML = data.transcripts.slice(0, 10).map(t =>
      `<li class="clickable" onclick="setTopic(${JSON.stringify(t.topic || t.title)})">` +
      `<strong>${esc(t.title)}</strong> <span class="muted">(${t.word_count} words, ${esc((t.created_at||'').slice(0,10))})</span></li>`
    ).join('');
  } catch (_) {}
}

async function loadContentStatus() {
  try {
    const s = await apiFetch('/api/content/status');
    document.getElementById('content_status').innerHTML =
      `<span class="badge badge-ok">${s.transcripts} transcripts</span> ` +
      `<span class="badge badge-ok">${s.videos} videos</span> ` +
      (s.llm_enabled ? '<span class="badge badge-ok">LLM on</span>' : '<span class="badge badge-warn">LLM off</span>') +
      `<span class="muted" style="margin-left:8px;">Daily post: ${s.daily_post_schedule}</span>`;
  } catch (_) {}
}

// ---------- Finance inputs ----------
function assetRow(a = {}) {
  const d = document.createElement('div'); d.className = 'fin-row fin-asset';
  d.innerHTML =
    `<input class="a-name" placeholder="Asset name" value="${escAttr(a.name || '')}"/>` +
    `<input class="a-value" type="number" placeholder="Value" value="${a.value ?? ''}"/>` +
    `<select class="a-kind">` +
    ['cash','investment','property','other'].map(k => `<option value="${k}" ${a.kind===k?'selected':''}>${k}</option>`).join('') +
    `</select><button type="button" class="btn-danger" onclick="this.parentElement.remove()">×</button>`;
  return d;
}
function debtRow(d0 = {}) {
  const d = document.createElement('div'); d.className = 'fin-row fin-debt';
  d.innerHTML =
    `<input class="d-name" placeholder="Debt name" value="${escAttr(d0.name || '')}"/>` +
    `<input class="d-balance" type="number" placeholder="Balance" value="${d0.balance ?? ''}"/>` +
    `<input class="d-apr" type="number" placeholder="APR %" value="${d0.apr ?? ''}"/>` +
    `<input class="d-min" type="number" placeholder="Min pay" value="${d0.min_payment ?? ''}"/>` +
    `<button type="button" class="btn-danger" onclick="this.parentElement.remove()">×</button>`;
  return d;
}
function addAsset(a) { document.getElementById('fin_assets').appendChild(assetRow(a)); }
function addDebt(d) { document.getElementById('fin_debts').appendChild(debtRow(d)); }

function collectProfile() {
  const assets = [...document.querySelectorAll('.fin-asset')].map(r => ({
    name: r.querySelector('.a-name').value,
    value: parseFloat(r.querySelector('.a-value').value) || 0,
    kind: r.querySelector('.a-kind').value,
  })).filter(a => a.name);
  const debts = [...document.querySelectorAll('.fin-debt')].map(r => ({
    name: r.querySelector('.d-name').value,
    balance: parseFloat(r.querySelector('.d-balance').value) || 0,
    apr: parseFloat(r.querySelector('.d-apr').value) || 0,
    min_payment: parseFloat(r.querySelector('.d-min').value) || 0,
  })).filter(d => d.name);
  return {
    monthly_income: parseFloat(document.getElementById('fin_income').value) || 0,
    monthly_expenses: parseFloat(document.getElementById('fin_expenses').value) || 0,
    extra_debt_payment: parseFloat(document.getElementById('fin_extra').value) || 0,
    age: parseInt(document.getElementById('fin_age').value) || 0,
    retirement_age: parseInt(document.getElementById('fin_ret_age').value) || 65,
    monthly_retirement_contribution: parseFloat(document.getElementById('fin_ret_contrib').value) || 0,
    assets, debts,
  };
}

function fillForm(p) {
  document.getElementById('fin_income').value = p.monthly_income || '';
  document.getElementById('fin_expenses').value = p.monthly_expenses || '';
  document.getElementById('fin_extra').value = p.extra_debt_payment || '';
  document.getElementById('fin_age').value = p.age || '';
  document.getElementById('fin_ret_age').value = p.retirement_age || '';
  document.getElementById('fin_ret_contrib').value = p.monthly_retirement_contribution || '';
  document.getElementById('fin_assets').innerHTML = '';
  document.getElementById('fin_debts').innerHTML = '';
  (p.assets || []).forEach(addAsset);
  (p.debts || []).forEach(addDebt);
  if (!(p.assets || []).length) addAsset();
  if (!(p.debts || []).length) addDebt();
}

function renderFinance(data) {
  const hasData = (data.profile.assets || []).length || (data.profile.debts || []).length;
  document.getElementById('fin_empty').style.display = hasData ? 'none' : 'block';
  document.getElementById('fin_out').style.display = hasData ? 'block' : 'none';
  document.getElementById('overview_empty').style.display = hasData ? 'none' : 'block';
  document.getElementById('overview_stats').style.display = hasData ? 'block' : 'none';
  if (!hasData) return;

  document.getElementById('fin_networth').textContent = money(data.net_worth.net_worth);
  document.getElementById('fin_score').textContent = data.health.score + ' (' + data.health.grade + ')';
  document.getElementById('fin_surplus').textContent = money(data.health.metrics.monthly_surplus) + '/mo';
  document.getElementById('ov_networth').textContent = money(data.net_worth.net_worth);
  document.getElementById('ov_score').textContent = data.health.score + ' (' + data.health.grade + ')';
  document.getElementById('ov_surplus').textContent = money(data.health.metrics.monthly_surplus) + '/mo';

  const a = data.debt_plan.avalanche, s = data.debt_plan.snowball;
  const truncNote = (a.timeline_truncated || s.timeline_truncated)
    ? '<li class="muted">Chart shows first 120 months; minimum payments may not cover interest.</li>' : '';
  document.getElementById('fin_debtplan').innerHTML =
    `<ul><li><strong>Avalanche</strong> (highest APR first): ${esc(a.duration)}, interest ${money(a.total_interest)} ` +
    `<span class="muted">order: ${a.order.map(esc).join(' → ')}</span></li>` +
    `<li><strong>Snowball</strong> (smallest balance first): ${esc(s.duration)}, interest ${money(s.total_interest)}</li>` +
    `<li class="muted">Recommended: <strong>${esc(data.debt_plan.recommended)}</strong> — saves ${money(Math.abs(data.debt_plan.interest_saved_with_avalanche))} in interest</li>` +
    truncNote + `</ul>`;

  document.getElementById('fin_recs').innerHTML = data.health.recommendations
    .map(r => `<div class="rec ${esc(r.priority)}"><span class="tag">${esc(r.priority)}</span><br>${esc(r.text)}</div>`).join('');

  const hist = data.history || [];
  chart('chart_networth', {
    type: 'line',
    data: { labels: hist.map(h => h.date), datasets: [{
      label: 'Net worth', data: hist.map(h => h.value),
      borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,.15)', fill: true, tension: .3, pointRadius: 3 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { x: { grid: { color: GRID } }, y: { grid: { color: GRID }, ticks: { callback: v => '$' + (v/1000) + 'k' } } } }
  });
  const nb = data.net_worth;
  chart('chart_assets', {
    type: 'bar',
    data: { labels: ['Assets', 'Debts'], datasets: [{ data: [nb.total_assets, nb.total_debts],
      backgroundColor: ['#22c55e', '#f87171'] }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: GRID }, ticks: { callback: v => '$' + (v/1000) + 'k' } } } }
  });

  const maxLen = Math.max((a.timeline||[]).length, (s.timeline||[]).length);
  const labels = Array.from({length: maxLen}, (_, i) => 'Mo ' + (i + 1));
  chart('chart_debt', {
    type: 'line',
    data: { labels, datasets: [
      { label: 'Avalanche', data: a.timeline || [], borderColor: '#3b82f6', tension: .2, pointRadius: 0 },
      { label: 'Snowball', data: s.timeline || [], borderColor: '#facc15', tension: .2, pointRadius: 0 },
    ]},
    options: { maintainAspectRatio: false,
      scales: { x: { grid: { color: GRID } }, y: { grid: { color: GRID }, ticks: { callback: v => '$' + (v/1000) + 'k' } } } }
  });

  renderBudgetVsActual(data);
  renderRetirement(data.retirement);
}

function renderBudgetVsActual(data) {
  const cf = data.cashflow;
  const box = document.getElementById('budget_out');
  if (!cf || !cf.transaction_count) { box.style.display = 'none'; return; }
  box.style.display = 'block';
  const manualIn = data.profile.monthly_income;
  const manualOut = data.profile.monthly_expenses;
  const actualIn = cf.avg_monthly_income;
  const actualOut = cf.avg_monthly_expenses;
  document.getElementById('budget_rows').innerHTML =
    `<tr><td>Income</td><td>${money(manualIn)}</td><td>${money(actualIn)}</td>` +
    `<td style="color:${actualIn >= manualIn ? 'var(--green)' : 'var(--red)'}">${money(actualIn - manualIn)}</td></tr>` +
    `<tr><td>Expenses</td><td>${money(manualOut)}</td><td>${money(actualOut)}</td>` +
    `<td style="color:${actualOut <= manualOut ? 'var(--green)' : 'var(--red)'}">${money(actualOut - manualOut)}</td></tr>`;
}

function renderRetirement(r) {
  if (!r) return;
  document.getElementById('fin_ret_stat').textContent = r.on_track ? 'On track' : 'Behind';
  document.getElementById('fin_ret_stat').style.color = r.on_track ? 'var(--green)' : 'var(--red)';
  document.getElementById('ov_ret_stat').textContent = r.on_track ? 'On track' : 'Behind';
  document.getElementById('ov_ret_stat').style.color = r.on_track ? 'var(--green)' : 'var(--red)';
  if (!r.age) {
    document.getElementById('ret_out').style.display = 'none';
    document.getElementById('ret_empty').style.display = 'block';
    return;
  }
  document.getElementById('ret_empty').style.display = 'none';
  document.getElementById('ret_out').style.display = 'block';
  document.getElementById('ret_projected').textContent = money(r.projected_savings);
  document.getElementById('ret_needed').textContent = money(r.nest_egg_needed);
  document.getElementById('ret_badge').innerHTML = r.on_track
    ? '<span class="badge badge-ok">On track</span>'
    : '<span class="badge badge-warn">Behind</span>';
  document.getElementById('ret_recs').innerHTML = r.recommendations
    .map(x => `<div class="rec ${x.priority}"><span class="tag">${x.priority}</span><br>${x.text}</div>`).join('');
  const proj = r.projection || [];
  chart('chart_retirement', {
    type: 'line',
    data: { labels: proj.map(p => p.age), datasets: [
      { label: 'Projected balance', data: proj.map(p => p.balance), borderColor: '#8b5cf6',
        backgroundColor: 'rgba(139,92,246,.15)', fill: true, tension: .3, pointRadius: 0 },
      { label: 'Needed', data: proj.map(() => r.nest_egg_needed), borderColor: '#facc15',
        borderDash: [6,6], pointRadius: 0, fill: false } ] },
    options: { maintainAspectRatio: false,
      plugins: { legend: { display: true, labels: { boxWidth: 12 } },
        tooltip: { callbacks: { label: c => c.dataset.label + ': ' + money(c.parsed.y) } } },
      scales: { x: { title: { display: true, text: 'Age' }, grid: { color: GRID } },
        y: { grid: { color: GRID }, ticks: { callback: v => '$' + (v/1000) + 'k' } } } }
  });
}

async function saveFinance() {
  showAlert('finance_alert', '');
  try {
    const data = await apiFetch('/api/finance', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(collectProfile()) });
    renderFinance(data); renderCashflow(data);
  } catch (e) { showAlert('finance_alert', e.message, 'error'); }
}
async function loadSample() {
  showAlert('finance_alert', '');
  try {
    const data = await apiFetch('/api/finance/sample', {method: 'POST'});
    fillForm(data.profile); renderFinance(data); renderCashflow(data);
  } catch (e) { showAlert('finance_alert', e.message, 'error'); }
}

function renderCashflow(data) {
  const cf = data.cashflow;
  if (!cf || !cf.transaction_count) return;
  document.getElementById('cf_out').style.display = 'block';
  document.getElementById('cf_income').textContent = money(cf.total_income);
  document.getElementById('cf_expenses').textContent = money(cf.total_expenses);
  const net = document.getElementById('cf_net');
  net.textContent = money(cf.net_cashflow);
  net.style.color = cf.net_cashflow >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('cf_avg').textContent = `${money(cf.avg_monthly_income)} in / ${money(cf.avg_monthly_expenses)} out`;
  document.getElementById('cf_income_src').innerHTML = cf.income_by_source
    .map(s => `<li>${s.source} <span class="muted">${money(s.amount)}</span></li>`).join('') || '<li class="muted">—</li>';
  document.getElementById('cf_txns').innerHTML = (data.recent_transactions || []).slice(0, 8)
    .map(t => `<li>${t.date} ${t.description} <span class="muted">${t.category}</span> ` +
      `<span style="color:${t.amount>=0?'var(--green)':'var(--red)'}">${money(t.amount)}</span></li>`).join('');

  const cats = cf.expenses_by_category || [];
  chart('chart_categories', {
    type: 'doughnut',
    data: { labels: cats.map(c => c.category), datasets: [{ data: cats.map(c => c.amount), backgroundColor: PALETTE }] },
    options: { maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { boxWidth: 12 } },
      tooltip: { callbacks: { label: c => c.label + ': ' + money(c.parsed) } } } }
  });
  const bym = cf.by_month || [];
  chart('chart_cashflow', {
    type: 'bar',
    data: { labels: bym.map(m => m.month), datasets: [{ label: 'Net', data: bym.map(m => m.net),
      backgroundColor: bym.map(m => m.net >= 0 ? '#22c55e' : '#f87171') }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: GRID }, ticks: { callback: v => '$' + v } } } }
  });
  renderBudgetVsActual(data);
}

async function importFinance() {
  const input = document.getElementById('fin_file');
  const msg = document.getElementById('fin_import_msg');
  if (!input.files.length) { msg.textContent = 'Choose a file first.'; return; }
  msg.textContent = 'Importing…';
  const fd = new FormData(); fd.append('file', input.files[0]);
  try {
    const res = await fetch('/api/finance/import', {method: 'POST', body: fd});
    const data = await res.json();
    if (!res.ok) { msg.textContent = 'Error: ' + (data.detail || 'import failed'); return; }
    msg.textContent = `Imported ${data.imported.added} rows from ${data.imported.source}.`;
    fillForm(data.profile); renderFinance(data); renderCashflow(data);
  } catch (e) { msg.textContent = 'Error: ' + e.message; }
}

async function loadFinance() {
  try {
    const data = await apiFetch('/api/finance');
    fillForm(data.profile);
    renderFinance(data);
    renderCashflow(data);
  } catch (_) {}
}

// ---------- Plaid ----------
async function plaidStatus() {
  const connect = document.getElementById('plaid_connect');
  const sync = document.getElementById('plaid_sync');
  const msg = document.getElementById('plaid_msg');
  try {
    const s = await apiFetch('/api/finance/plaid/status');
    if (!s.configured) {
      connect.disabled = true;
      msg.textContent = 'Plaid not configured — add PLAID_CLIENT_ID and PLAID_SECRET to enable.';
      return;
    }
    connect.disabled = false;
    msg.textContent = `Plaid ready (${s.env}).` + (s.linked ? ' Bank linked.' : '');
    sync.style.display = s.linked ? 'inline-block' : 'none';
  } catch (e) {
    connect.disabled = true;
    msg.textContent = 'Could not load Plaid status: ' + e.message;
  }
}
async function plaidConnect() {
  const msg = document.getElementById('plaid_msg');
  msg.textContent = 'Opening Plaid…';
  try {
    const data = await apiFetch('/api/finance/plaid/link-token', {method: 'POST'});
    if (typeof Plaid === 'undefined') { msg.textContent = 'Plaid Link script not loaded.'; return; }
    const handler = Plaid.create({
      token: data.link_token,
      onSuccess: async (public_token) => {
        msg.textContent = 'Linking & pulling accounts…';
        const ex = await fetch('/api/finance/plaid/exchange', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({public_token}) });
        const d = await ex.json();
        if (!ex.ok) { msg.textContent = 'Error: ' + (d.detail || 'exchange failed'); return; }
        msg.textContent = `Linked! Pulled ${d.imported.added} transactions.`;
        fillForm(d.profile); renderFinance(d); renderCashflow(d); plaidStatus();
      },
      onExit: (err) => { if (err) msg.textContent = 'Plaid exited: ' + (err.display_message || err.error_message || ''); },
    });
    handler.open();
  } catch (e) { msg.textContent = 'Error: ' + e.message; }
}
async function plaidSync() {
  const msg = document.getElementById('plaid_msg');
  msg.textContent = 'Syncing…';
  try {
    const d = await apiFetch('/api/finance/plaid/sync', {method: 'POST'});
    msg.textContent = `Synced ${d.imported.added} transactions.`;
    fillForm(d.profile); renderFinance(d); renderCashflow(d);
  } catch (e) { msg.textContent = 'Error: ' + e.message; }
}

// ---------- Real estate ----------
const RE_KEY = 'gary_re_filters';
function saveReFilters() {
  localStorage.setItem(RE_KEY, JSON.stringify({
    city: document.getElementById('re_city').value,
    state: document.getElementById('re_state').value,
    radius: document.getElementById('re_radius').value,
    min_acres: document.getElementById('re_acres').value,
    max_price: document.getElementById('re_price').value,
    sort: document.getElementById('re_sort').value,
  }));
}
function loadReFilters() {
  try {
    const f = JSON.parse(localStorage.getItem(RE_KEY) || '{}');
    if (f.city) document.getElementById('re_city').value = f.city;
    if (f.state) document.getElementById('re_state').value = f.state;
    if (f.radius) document.getElementById('re_radius').value = f.radius;
    if (f.min_acres) document.getElementById('re_acres').value = f.min_acres;
    if (f.max_price) document.getElementById('re_price').value = f.max_price;
    if (f.sort) document.getElementById('re_sort').value = f.sort;
  } catch (_) {}
}

function sortListings(listings, sortBy) {
  const rows = [...listings];
  if (sortBy === 'price_asc') rows.sort((a, b) => a.price - b.price);
  else if (sortBy === 'price_desc') rows.sort((a, b) => b.price - a.price);
  else if (sortBy === 'acres_desc') rows.sort((a, b) => b.acres - a.acres);
  else if (sortBy === 'ppa') rows.sort((a, b) => (a.price / Math.max(a.acres, 0.01)) - (b.price / Math.max(b.acres, 0.01)));
  else if (sortBy === 'distance') rows.sort((a, b) => (a.distance_mi ?? 999) - (b.distance_mi ?? 999));
  return rows;
}

async function searchRealEstate() {
  const msg = document.getElementById('re_msg');
  const results = document.getElementById('re_results');
  saveReFilters();
  msg.textContent = 'Searching…'; results.innerHTML = '';
  const q = new URLSearchParams({
    city: document.getElementById('re_city').value || 'Cincinnati',
    state: document.getElementById('re_state').value || 'OH',
    radius: document.getElementById('re_radius').value || 25,
    min_acres: document.getElementById('re_acres').value || 5,
    max_price: document.getElementById('re_price').value || 350000,
  });
  try {
    const data = await apiFetch('/api/realestate?' + q.toString());
    const src = data.source === 'rentcast'
      ? '<span class="badge badge-ok">live</span>'
      : '<span class="badge badge-warn">sample data — add RENTCAST_API_KEY for live</span>';
    msg.innerHTML = `${data.count} listings within ${data.filters.radius} mi of ` +
      `${data.filters.city}, ${data.filters.state} · ${data.filters.min_acres}+ acres · ` +
      `under ${money(data.filters.max_price)} ${src}`;
    const sorted = sortListings(data.listings, document.getElementById('re_sort').value);
    results.innerHTML = sorted.map(l =>
      `<li><a href="${l.url}" target="_blank">${l.address}, ${l.city} ${l.state}</a> ` +
      `<span style="color:var(--green);font-weight:700;">${money(l.price)}</span> ` +
      `<span class="muted">${l.acres} acres` +
      (l.beds ? ` · ${l.beds}bd/${l.baths||'?'}ba` : '') +
      (l.distance_mi != null ? ` · ${l.distance_mi} mi` : '') +
      ` · ${money(l.price / Math.max(l.acres, 0.01))}/acre` +
      (l.listed_date ? ` · listed ${l.listed_date}` : '') + `</span></li>`
    ).join('') || '<li class="muted">No matching listings.</li>';
  } catch (e) { msg.textContent = 'Error: ' + e.message; }
}

// ---------- Wire buttons ----------
document.getElementById('btn_generate')?.addEventListener('click', () =>
  withLoading(document.getElementById('btn_generate'), generate));
document.getElementById('btn_pipeline')?.addEventListener('click', () =>
  withLoading(document.getElementById('btn_pipeline'), runPipeline));
document.getElementById('btn_save_finance')?.addEventListener('click', () =>
  withLoading(document.getElementById('btn_save_finance'), saveFinance));
document.getElementById('btn_sample')?.addEventListener('click', () =>
  withLoading(document.getElementById('btn_sample'), loadSample));
document.getElementById('btn_search_re')?.addEventListener('click', () =>
  withLoading(document.getElementById('btn_search_re'), searchRealEstate));

// ---------- init ----------
loadReFilters();
loadTrends('stocks', 'stocks');
loadTrends('crypto', 'crypto');
loadYouTube();
loadVideos();
loadTranscripts();
loadFinance();
plaidStatus();
loadContentStatus();
searchRealEstate();
