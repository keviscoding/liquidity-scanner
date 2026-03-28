/* ── Scan Type Selector ────────────────────────────────────────────────────── */
let currentScanType = 'standard';

function setScanType(type) {
  currentScanType = type;
  document.querySelectorAll('.scan-type-option').forEach(el => el.classList.remove('selected'));
  document.querySelector(`.scan-type-option input[value="${type}"]`)?.closest('.scan-type-option')?.classList.add('selected');

  const agentOpts = document.getElementById('agentOptions');
  const dryRunGroup = document.getElementById('dryRunGroup');
  const apiOptions = document.getElementById('apiOptions');
  const seedGroup = document.getElementById('seedGroup');

  if (agentOpts) agentOpts.style.display = type === 'agent' ? 'block' : 'none';
  if (dryRunGroup) dryRunGroup.style.display = (type === 'rescan' || type === 'autonomous') ? 'none' : 'block';
  if (apiOptions) apiOptions.style.display = (type === 'rescan' || type === 'autonomous' || document.getElementById('dryRun')?.checked) ? 'none' : 'block';
  if (seedGroup) seedGroup.style.display = (type === 'rescan' || type === 'autonomous') ? 'none' : 'block';
}

/* ── Modal ────────────────────────────────────────────────────────────────── */
function openModal() {
  document.getElementById('modal').classList.add('open');
}
function closeModal() {
  document.getElementById('modal').classList.remove('open');
}
function closeModalOutside(e) {
  if (e.target === document.getElementById('modal')) closeModal();
}
function toggleDryRun() {
  const dry = document.getElementById('dryRun').checked;
  document.getElementById('apiOptions').style.display = dry ? 'none' : 'block';
}
function updateSearchLabel() {
  document.getElementById('searchLabel').textContent = document.getElementById('maxSearches').value;
}
function updateSeedLabel() {
  document.getElementById('seedLabel').textContent = document.getElementById('maxSeeds').value;
}

async function startScan() {
  const dryRun = document.getElementById('dryRun')?.checked ?? false;
  const maxSearches = parseInt(document.getElementById('maxSearches')?.value ?? '50');
  const maxSeeds = parseInt(document.getElementById('maxSeeds')?.value ?? '25');
  const extraRaw = document.getElementById('extraSeeds')?.value ?? '';
  const extraSeeds = extraRaw.split(',').map(s => s.trim()).filter(Boolean);
  const agentDirection = document.getElementById('agentDirection')?.value ?? '';

  const btn = document.querySelector('.modal-footer .btn-primary');
  btn.textContent = 'Starting...';
  btn.disabled = true;

  try {
    const res = await fetch('/api/scans', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dry_run: dryRun,
        max_searches: maxSearches,
        max_seeds: maxSeeds,
        extra_seeds: extraSeeds,
        scan_type: currentScanType,
        agent_direction: agentDirection,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      alert('Error: ' + (err.detail || 'Unknown error'));
      btn.textContent = 'Start Scan';
      btn.disabled = false;
      return;
    }

    const data = await res.json();
    window.location.href = `/scan/${data.scan_id}`;
  } catch (e) {
    alert('Network error: ' + e.message);
    btn.textContent = 'Start Scan';
    btn.disabled = false;
  }
}

/* ── Progress SSE ─────────────────────────────────────────────────────────── */
function startProgressStream(scanId) {
  const es = new EventSource(`/api/scans/${scanId}/stream`);
  const fill = document.getElementById('progressFill');
  const msg  = document.getElementById('progressMsg');
  const pct  = document.getElementById('progressPct');
  const log  = document.getElementById('progressLog');

  es.onmessage = (e) => {
    const data = JSON.parse(e.data);

    if (data.done) {
      es.close();
      if (data.status === 'completed') {
        setTimeout(() => window.location.reload(), 800);
      } else {
        if (msg) msg.textContent = 'Scan failed. Check the error above.';
        if (pct) pct.textContent = '';
      }
      return;
    }

    const p = data.pct ?? 0;
    if (fill) fill.style.width = p + '%';
    if (msg)  msg.textContent  = data.message || '';
    if (pct)  pct.textContent  = p + '%';
    if (log) {
      const line = document.createElement('div');
      line.textContent = data.message;
      log.appendChild(line);
      log.scrollTop = log.scrollHeight;
      while (log.children.length > 40) log.removeChild(log.firstChild);
    }

    // Live-reload results table when a new niche is found
    if (data.message && data.message.startsWith('Found niche #')) {
      refreshResultsTable(scanId);
    }
  };

  es.onerror = () => { es.close(); };
}

/* ── Live results refresh during scan ──────────────────────────────────── */
async function refreshResultsTable(scanId) {
  try {
    const resp = await fetch(`/api/results/${scanId}`);
    if (!resp.ok) return;
    const results = await resp.json();
    const tbody = document.getElementById('tableBody');
    if (!tbody || !results.length) return;

    tbody.innerHTML = '';
    results.forEach((r, i) => {
      const row = document.createElement('tr');
      row.className = 'result-row';
      row.dataset.term = r.term;
      row.dataset.overall = r.overall_score;
      row.dataset.liquidity = r.liquidity_score;
      row.dataset.velocity = r.velocity_score;
      row.innerHTML = `
        <td>${i + 1}</td>
        <td class="term-cell">${r.term}</td>
        <td><span class="score ${scoreClass(r.overall_score)}">${r.overall_score}</span></td>
        <td>${r.liquidity_score}</td>
        <td>${r.velocity_score}</td>
        <td>${r.videos_last_30d || 0}</td>
        <td>${Math.round(r.avg_views || 0).toLocaleString()}</td>
        <td>${Math.round(r.avg_channel_subs || 0).toLocaleString()}</td>
        <td>${r.small_channels_pct || 0}%</td>
      `;
      row.onclick = () => showDetail(r);
      tbody.appendChild(row);
    });
  } catch(e) {}
}

function scoreClass(s) {
  if (s >= 75) return 'score-high';
  if (s >= 50) return 'score-mid';
  return 'score-low';
}

/* ── Results table: filter & sort ────────────────────────────────────────── */
function filterTable() {
  const q = document.getElementById('filterInput')?.value.toLowerCase() ?? '';
  const rows = document.querySelectorAll('#tableBody .result-row');
  rows.forEach(row => {
    const term = row.dataset.term ?? '';
    row.style.display = term.toLowerCase().includes(q) ? '' : 'none';
  });
}

function sortTable() {
  const key = document.getElementById('sortSelect')?.value ?? 'overall';
  const tbody = document.getElementById('tableBody');
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll('.result-row'));
  rows.sort((a, b) => {
    if (key === 'confidence') {
      const order = {'high': 0, 'medium': 1, 'low': 2, '': 3, 'unknown': 3};
      return (order[a.dataset.confidence || ''] || 3) - (order[b.dataset.confidence || ''] || 3);
    }
    return parseFloat(b.dataset[key] ?? '0') - parseFloat(a.dataset[key] ?? '0');
  });
  rows.forEach(r => tbody.appendChild(r));
}

/* ── Detail drawer ────────────────────────────────────────────────────────── */
function scoreClass(v) {
  if (v >= 75) return 'score-great';
  if (v >= 55) return 'score-good';
  if (v >= 35) return 'score-ok';
  if (v >= 10) return 'score-low';
  return 'score-none';
}

function confClass(c) {
  if (c === 'high') return 'conf-high';
  if (c === 'medium') return 'conf-medium';
  return 'conf-low';
}

function openDetail(idx) {
  if (typeof results === 'undefined') return;
  const r = results[idx];
  if (!r) return;

  // Try to find AI analysis for this term
  const ai = (typeof aiAnalyses !== 'undefined')
    ? aiAnalyses.find(a => a.term.toLowerCase() === r.term.toLowerCase())
    : null;

  const pathChips = (r.parent_chain || '').split(' > ')
    .filter(Boolean)
    .map(p => `<span class="path-chip">${p}</span>`)
    .join('');

  let html = `<div class="drawer-term">${r.term}</div>`;

  // AI confidence badge
  if (ai && ai.confidence) {
    html += `<div class="ai-conf-badge ${confClass(ai.confidence)}">${ai.confidence.toUpperCase()} CONFIDENCE</div>`;
  }

  // Scores grid
  html += `
    <div class="scores-grid">
      <div class="score-cell">
        <div class="score-cell-label">Overall</div>
        <div class="score-cell-val ${scoreClass(r.overall_score)}">${r.overall_score ?? '—'}</div>
      </div>
      <div class="score-cell">
        <div class="score-cell-label">Liquidity</div>
        <div class="score-cell-val ${scoreClass(r.liquidity_score)}">${Math.round(r.liquidity_score ?? 0)}</div>
      </div>
      <div class="score-cell">
        <div class="score-cell-label">Velocity</div>
        <div class="score-cell-val ${scoreClass(r.velocity_score)}">${Math.round(r.velocity_score ?? 0)}</div>
      </div>
      <div class="score-cell">
        <div class="score-cell-label">Recency</div>
        <div class="score-cell-val ${scoreClass(r.recency_score)}">${Math.round(r.recency_score ?? 0)}</div>
      </div>
    </div>`;

  // AI Briefing
  if (ai && ai.full_briefing) {
    html += `
      <div class="detail-section ai-brief-section">
        <div class="detail-section-title">AI Analysis</div>
        <div class="ai-brief">${ai.full_briefing.replace(/\n/g, '<br>').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')}</div>
      </div>`;
  }

  // Buying intent signals
  if (ai && ai.buying_intent && ai.buying_intent.length > 0) {
    html += `
      <div class="detail-section">
        <div class="detail-section-title">Buying Intent Signals</div>
        <div class="tag-row">${ai.buying_intent.map(s => `<span class="intent-tag">${s}</span>`).join('')}</div>
      </div>`;
  }

  // Monetization angles
  if (ai && ai.monetization && ai.monetization.length > 0) {
    html += `
      <div class="detail-section">
        <div class="detail-section-title">Monetization Angles</div>
        <div class="tag-row">${ai.monetization.map(s => `<span class="money-tag">${s}</span>`).join('')}</div>
      </div>`;
  }

  // Risks
  if (ai && ai.risks && ai.risks.length > 0) {
    html += `
      <div class="detail-section">
        <div class="detail-section-title">Risks</div>
        <div class="tag-row">${ai.risks.map(s => `<span class="risk-tag">${s}</span>`).join('')}</div>
      </div>`;
  }

  // Action plan
  if (ai && ai.action_plan && ai.action_plan.length > 0) {
    html += `
      <div class="detail-section">
        <div class="detail-section-title">Action Plan</div>
        <div class="action-list">${ai.action_plan.map((s, i) => `<div class="action-item"><span class="action-num">${i+1}</span>${s}</div>`).join('')}</div>
      </div>`;
  }

  // Raw metrics
  html += `
    <div class="detail-section">
      <div class="detail-section-title">Metrics</div>
      <div class="detail-row"><span>Videos (30 days)</span><span>${r.videos_last_30d ?? 0}</span></div>
      <div class="detail-row"><span>Avg views / video</span><span>${(r.avg_views ?? 0).toLocaleString(undefined, {maximumFractionDigits:0})}</span></div>
      <div class="detail-row"><span>Avg views / day</span><span>${(r.avg_views_per_day ?? 0).toLocaleString(undefined, {maximumFractionDigits:0})}</span></div>
      <div class="detail-row"><span>Avg channel subs</span><span>${(r.avg_channel_subs ?? 0).toLocaleString(undefined, {maximumFractionDigits:0})}</span></div>
      <div class="detail-row"><span>View / sub ratio</span><span style="color:${(r.view_to_sub_ratio??0)>=5?'#22c55e':'inherit'};font-weight:700">${(r.view_to_sub_ratio ?? 0).toFixed(1)}x</span></div>
      <div class="detail-row"><span>Small channels</span><span>${(r.small_channels_pct ?? 0).toFixed(0)}%</span></div>
    </div>`;

  if (r.best_video_title) {
    html += `
      <div class="detail-section">
        <div class="detail-section-title">Best Video</div>
        <div class="best-video-card">
          <div class="best-video-title">${r.best_video_title}</div>
          <div class="best-video-meta">${(r.best_video_views ?? 0).toLocaleString()} views · ${(r.best_video_channel_subs ?? 0).toLocaleString()} subs</div>
        </div>
      </div>`;
  }

  if (pathChips) {
    html += `<div class="detail-section"><div class="detail-section-title">Discovery Path</div><div>${pathChips}</div></div>`;
  }

  document.getElementById('drawerContent').innerHTML = html;
  document.getElementById('drawer').classList.add('open');
}

function closeDrawer() {
  document.getElementById('drawer')?.classList.remove('open');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeModal(); closeDrawer(); }
});
