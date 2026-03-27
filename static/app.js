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

  const btn = document.querySelector('.modal-footer .btn-primary');
  btn.textContent = 'Starting...';
  btn.disabled = true;

  try {
    const res = await fetch('/api/scans', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dry_run: dryRun, max_searches: maxSearches, max_seeds: maxSeeds, extra_seeds: extraSeeds }),
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
        // Reload to show results
        setTimeout(() => window.location.reload(), 800);
      } else {
        msg.textContent = 'Scan failed. Check the error above.';
        pct.textContent = '';
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
      // Keep log from getting too long
      while (log.children.length > 30) log.removeChild(log.firstChild);
    }
  };

  es.onerror = () => { es.close(); };
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
    const aVal = parseFloat(a.dataset[key] ?? '0');
    const bVal = parseFloat(b.dataset[key] ?? '0');
    return bVal - aVal;
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

function openDetail(idx) {
  if (typeof results === 'undefined') return;
  const r = results[idx];
  if (!r) return;

  const pathChips = (r.parent_chain || '').split(' > ')
    .filter(Boolean)
    .map(p => `<span class="path-chip">${p}</span>`)
    .join('');

  const html = `
    <div class="drawer-term">${r.term}</div>

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
    </div>

    <div class="detail-section">
      <div class="detail-section-title">Metrics</div>
      <div class="detail-row"><span>Videos (30 days)</span><span>${r.videos_last_30d ?? 0}</span></div>
      <div class="detail-row"><span>Avg views / video</span><span>${(r.avg_views ?? 0).toLocaleString(undefined, {maximumFractionDigits:0})}</span></div>
      <div class="detail-row"><span>Avg views / day</span><span>${(r.avg_views_per_day ?? 0).toLocaleString(undefined, {maximumFractionDigits:0})}</span></div>
      <div class="detail-row"><span>Avg channel subs</span><span>${(r.avg_channel_subs ?? 0).toLocaleString(undefined, {maximumFractionDigits:0})}</span></div>
      <div class="detail-row"><span>View / sub ratio</span><span style="color:${(r.view_to_sub_ratio??0)>=5?'#22c55e':'inherit'};font-weight:700">${(r.view_to_sub_ratio ?? 0).toFixed(1)}x</span></div>
      <div class="detail-row"><span>Small channels</span><span>${(r.small_channels_pct ?? 0).toFixed(0)}%</span></div>
      <div class="detail-row"><span>Total search results</span><span>${(r.total_results ?? 0).toLocaleString()}</span></div>
    </div>

    ${r.best_video_title ? `
    <div class="detail-section">
      <div class="detail-section-title">Best Performing Video</div>
      <div class="best-video-card">
        <div class="best-video-title">${r.best_video_title}</div>
        <div class="best-video-meta">
          ${(r.best_video_views ?? 0).toLocaleString()} views
          · ${(r.best_video_channel_subs ?? 0).toLocaleString()} subs on channel
        </div>
      </div>
    </div>` : ''}

    ${pathChips ? `
    <div class="detail-section">
      <div class="detail-section-title">Discovery Path</div>
      <div>${pathChips}</div>
    </div>` : ''}
  `;

  document.getElementById('drawerContent').innerHTML = html;
  document.getElementById('drawer').classList.add('open');
}

function closeDrawer() {
  document.getElementById('drawer')?.classList.remove('open');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeModal(); closeDrawer(); }
});
