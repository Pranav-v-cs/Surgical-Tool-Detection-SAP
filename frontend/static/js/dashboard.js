/* ── dashboard.js — WebSocket client + live UI ── */

const API = '';
const WS_URL = `ws://${location.host}/ws`;

let ws = null;
let wsRetryDelay = 1500;
let sessionStartTime = null;
let timerInterval = null;
let currentUser = null;
let currentSession = null;
let toolsSavedForSession = false;
let isUploadMode = false;    // true after an image upload — WS frames won't overwrite until camera is toggled ON

// ── Auth helpers ──────────────────────────────────────────────────
function getToken() { return localStorage.getItem('sap_token'); }
function getUser() { return JSON.parse(localStorage.getItem('sap_user') || 'null'); }

function authHeaders() {
  return { 'Authorization': `Bearer ${getToken()}`, 'Content-Type': 'application/json' };
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, { headers: authHeaders(), ...opts });
  if (res.status === 401) { logout(); return null; }
  return res;
}

function logout() {
  localStorage.removeItem('sap_token');
  localStorage.removeItem('sap_user');
  location.href = '/';
}

// ── Camera toggle ─────────────────────────────────────────────────
let cameraIsPaused = false;

async function toggleCamera() {
  const res = await fetch('/detect/camera/toggle', { method: 'POST', headers: authHeaders() });
  if (!res || !res.ok) { showToast('Toggle failed', 'error'); return; }
  const data = await res.json();
  cameraIsPaused = data.camera_paused;
  // Switching camera ON clears upload-mode so live frames take over again
  if (!cameraIsPaused) {
    isUploadMode = false;
    const feed = document.getElementById('camera-feed');
    const placeholder = document.getElementById('camera-placeholder');
    if (feed) { feed.src = ''; feed.style.display = 'none'; }
    if (placeholder) placeholder.style.display = 'flex';
  }
  updateCameraToggleUI();
}

function updateCameraToggleUI() {
  const btn = document.getElementById('btn-cam-toggle');
  const badge = document.getElementById('cam-source-badge');
  if (!btn) return;

  if (cameraIsPaused) {
    btn.className = 'btn btn-cam-off active';
    btn.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="1" y1="1" x2="23" y2="23"/>
        <path d="M21 21H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3m3-3h6l2 3h4a2 2 0 0 1 2 2v9.34"/>
      </svg>
      Camera OFF`;
    if (badge) badge.innerHTML = `<span class="pulse-dot idle"></span> <span style="color:var(--text-muted)">Paused</span>`;
  } else {
    btn.className = 'btn btn-cam-on active';
    btn.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
      </svg>
      Camera ON`;
    if (badge) badge.innerHTML = `<span class="pulse-dot active"></span> <span style="color:var(--accent)">Webcam</span>`;
  }
}

// ── Image upload detection ────────────────────────────────────────
async function uploadImage(event) {
  const file = event.target.files[0];
  if (!file) return;

  // Show loading state
  const statusEl = document.getElementById('upload-status');
  const badge = document.getElementById('cam-source-badge');
  const uploadLbl = document.querySelector('.upload-label');

  if (statusEl) { statusEl.style.display = 'block'; statusEl.textContent = 'Running detection…'; }
  if (uploadLbl) uploadLbl.style.opacity = '0.5';

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/detect/upload', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${getToken()}` },
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || 'Upload failed', 'error');
      return;
    }

    const data = await res.json();

    // Show annotated image in the feed
    const feed = document.getElementById('camera-feed');
    const placeholder = document.getElementById('camera-placeholder');
    if (feed && data.frame) {
      feed.src = `data:image/jpeg;base64,${data.frame}`;
      feed.style.display = 'block';
      if (placeholder) placeholder.style.display = 'none';
      isUploadMode = true;  // keep this image visible until camera is toggled ON
    }

    // Update tool cards
    handleDetection({ ...data, type: 'detection' });

    // Update source badge
    if (badge) badge.innerHTML = `<span class="pulse-dot" style="background:var(--info)"></span> <span style="color:var(--info)">Image: ${file.name.slice(0, 16)}${file.name.length > 16 ? '…' : ''}</span>`;

    showToast(`${data.tool_count} tool${data.tool_count !== 1 ? 's' : ''} detected`, 'success');

    if (statusEl) statusEl.style.display = 'none';
  } catch {
    showToast('Upload error', 'error');
    if (statusEl) statusEl.style.display = 'none';
  } finally {
    if (uploadLbl) uploadLbl.style.opacity = '1';
    // Reset file input so same file can be re-uploaded
    event.target.value = '';
  }
}

// Expose globally
window.toggleCamera = toggleCamera;
window.uploadImage = uploadImage;



// ── Init ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  const token = getToken();
  if (!token) { location.href = '/'; return; }

  currentUser = getUser();

  // Render user info
  document.getElementById('user-name').textContent = currentUser?.username ?? '—';
  const roleEl = document.getElementById('user-role');
  if (roleEl && currentUser?.role) {
    roleEl.className = `badge badge-${currentUser.role}`;
    roleEl.textContent = currentUser.role;
  }

  // Build 26 tool cards
  buildToolGrid();

  // Check for active session
  await refreshActiveSession();

  // Connect WebSocket
  connectWS();

  // Load history
  loadHistory();

  // Load tool stats
  loadToolStats();

  // Clock
  setInterval(updateClock, 1000);
  updateClock();
});

// ── Tool grid ─────────────────────────────────────────────────────
function buildToolGrid() {
  const grid = document.getElementById('tools-grid');
  if (!grid) return;
  grid.innerHTML = '';
  for (let i = 1; i <= 26; i++) {
    const card = document.createElement('div');
    card.className = 'tool-card';
    card.id = `tool-${i}`;
    card.innerHTML = `
      <div class="tool-num">T-${String(i).padStart(2, '0')}</div>
      <div class="tool-name">Tool ${i}</div>
      <div class="tool-conf" id="conf-${i}">—</div>
      <div class="conf-bar-track"><div class="conf-bar-fill" id="bar-${i}"></div></div>
    `;
    grid.appendChild(card);
  }
}

// ── WebSocket ─────────────────────────────────────────────────────
function connectWS() {
  updateWSStatus('connecting');
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    updateWSStatus('connected');
    wsRetryDelay = 1500;
  };

  ws.onclose = () => {
    updateWSStatus('disconnected');
    setTimeout(connectWS, wsRetryDelay);
    wsRetryDelay = Math.min(wsRetryDelay * 1.5, 10000);
  };

  ws.onerror = () => updateWSStatus('disconnected');

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'detection') handleDetection(data);
  };
}

function updateWSStatus(status) {
  const el = document.getElementById('ws-status');
  if (!el) return;
  const configs = {
    connected: { dot: 'active', text: 'Live', color: 'var(--accent)' },
    connecting: { dot: 'idle', text: 'Connecting…', color: 'var(--warn)' },
    disconnected: { dot: 'danger', text: 'Disconnected', color: 'var(--danger)' },
  };
  const c = configs[status] || configs.disconnected;
  el.innerHTML = `<span class="pulse-dot ${c.dot}"></span> <span style="color:${c.color}">${c.text}</span>`;
}

// ── Detection handler ─────────────────────────────────────────────
let detectedSet = new Set();
let pendingDetection = null;
let renderScheduled = false;
let lastLiveListSignature = '';
let lastBubbleCount = null;
const toolCardCache = new Map();

function getToolEls(id) {
  if (!toolCardCache.has(id)) {
    toolCardCache.set(id, {
      card: document.getElementById(`tool-${id}`),
      conf: document.getElementById(`conf-${id}`),
      bar: document.getElementById(`bar-${id}`),
    });
  }
  return toolCardCache.get(id);
}

function handleDetection(data) {
  // While in upload mode, ignore WebSocket frames (they have 0 detections from simulated camera).
  // Only allow through if it's a fresh upload (source === 'upload').
  if (isUploadMode && data.source !== 'upload') return;

  pendingDetection = data;
  if (renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    if (!pendingDetection) return;
    renderDetection(pendingDetection);
    pendingDetection = null;
  });
}

function renderDetection(data) {
  // Update camera feed — skip if user uploaded an image (stays until Camera ON is clicked)
  const feed = document.getElementById('camera-feed');
  if (feed && data.frame && !isUploadMode) {
    feed.src = `data:image/jpeg;base64,${data.frame}`;
    feed.style.display = 'block';
    const placeholder = document.getElementById('camera-placeholder');
    if (placeholder) placeholder.style.display = 'none';
  }

  // Determine which tools are newly detected vs. gone
  const nowDetected = new Set(data.detections.map(d => d.tool_id));
  const confidenceMap = {};
  data.detections.forEach(d => { confidenceMap[d.tool_id] = d.confidence; });

  // Clear previously-detected tools that are no longer visible
  detectedSet.forEach(id => {
    if (!nowDetected.has(id)) {
      const { card, conf, bar } = getToolEls(id);
      if (card) {
        card.classList.remove('detected');
        if (conf) conf.textContent = '—';
        if (bar) bar.style.width = '0%';
      }
    }
  });

  // Light up currently-detected tools
  nowDetected.forEach(id => {
    const { card, conf: confEl, bar } = getToolEls(id);
    if (!card) return;
    const conf = confidenceMap[id];
    const wasDetected = detectedSet.has(id);
    if (!wasDetected) card.classList.add('detected');
    if (confEl) confEl.textContent = `${(conf * 100).toFixed(0)}%`;
    if (bar) bar.style.width = `${conf * 100}%`;
  });

  detectedSet = nowDetected;

  // Update count
  const countEl = document.getElementById('detection-count');
  if (countEl) countEl.textContent = data.tool_count;

  // Update live tools list in the left panel
  const liveList = document.getElementById('live-tools-list');
  if (liveList) {
    const liveSignature = data.detections
      .map(d => `${d.tool_id}:${Math.round(d.confidence * 100)}`)
      .join('|');

    if (liveSignature !== lastLiveListSignature) {
      lastLiveListSignature = liveSignature;
      if (data.detections.length === 0) {
        liveList.innerHTML = `<div class="stat-row"><span class="stat-label" style="color:var(--text-muted)">No tools in frame</span></div>`;
      } else {
        liveList.innerHTML = data.detections
          .sort((a, b) => b.confidence - a.confidence)
          .map(d => `
            <div class="stat-row">
              <span class="stat-label">${d.name}</span>
              <span class="stat-value" style="color:var(--accent);font-size:0.8rem">${(d.confidence * 100).toFixed(0)}% conf</span>
            </div>`)
          .join('');
      }
    }
  }

  // Pulse only when the count changes; forcing layout every frame is janky.
  const bubble = document.getElementById('count-bubble');
  if (bubble && lastBubbleCount !== data.tool_count) {
    lastBubbleCount = data.tool_count;
    bubble.classList.remove('pop');
    requestAnimationFrame(() => bubble.classList.add('pop'));
  }
}

// ── Session controls ──────────────────────────────────────────────
async function refreshActiveSession() {
  const res = await fetch('/surgery/active');
  const session = await res.json();
  currentSession = session;

  const noSession = document.getElementById('no-session');
  const hasSession = document.getElementById('has-session');
  const startBtn = document.getElementById('btn-start');
  const endBtn = document.getElementById('btn-end');

  if (session) {
    if (noSession) noSession.style.display = 'none';
    if (hasSession) hasSession.style.display = 'block';
    document.getElementById('sess-or').textContent = session.or_name;
    document.getElementById('sess-surgeon').textContent = session.surgeon_name;
    // Append 'Z' so JS parses as UTC (server returns naive UTC strings)
    const startUTC = session.started_at.endsWith('Z')
      ? session.started_at
      : session.started_at + 'Z';
    startSessionTimer(new Date(startUTC));
    if (startBtn) startBtn.style.display = 'none';
    if (endBtn) endBtn.style.display = 'flex';
    resetReconciliationPanel(false);

  } else {
    if (noSession) noSession.style.display = 'block';
    if (hasSession) hasSession.style.display = 'none';
    stopSessionTimer();
    if (startBtn) startBtn.style.display = 'flex';
    if (endBtn) endBtn.style.display = 'none';
    resetReconciliationPanel(true);

  }
}

async function startSurgery() {
  const orName = document.getElementById('or-name').value.trim() || 'OR-1';
  const surgeonName = document.getElementById('surgeon-name').value.trim() || 'Surgeon';

  const res = await apiFetch('/surgery/start', {
    method: 'POST',
    body: JSON.stringify({ or_name: orName, surgeon_name: surgeonName }),
  });
  if (!res) return;
  if (res.ok) {
    showToast('Surgery session started', 'success');
    await refreshActiveSession();
    loadHistory();
  } else {
    showToast('Failed to start session', 'error');
  }
}

async function endSurgery() {
  const res = await apiFetch('/surgery/end', { method: 'POST' });
  if (!res) return;
  if (res.ok) {
    showToast('Surgery session ended', 'success');
    await refreshActiveSession();
    loadHistory();
  } else {
    showToast('Failed to end session', 'error');
  }
}

// Expose globally for onclick
window.startSurgery = startSurgery;
window.endSurgery = endSurgery;
window.logout = logout;
window.saveTools = saveTools;
window.checkTools = checkTools;

// ── Timer ─────────────────────────────────────────────────────────
function startSessionTimer(startDate) {
  stopSessionTimer();
  sessionStartTime = startDate;
  timerInterval = setInterval(() => {
    const secs = Math.floor((Date.now() - sessionStartTime.getTime()) / 1000);
    const h = String(Math.floor(secs / 3600)).padStart(2, '0');
    const m = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
    const s = String(secs % 60).padStart(2, '0');
    const el = document.getElementById('session-timer');
    if (el) el.textContent = `${h}:${m}:${s}`;
  }, 1000);
}
function stopSessionTimer() {
  clearInterval(timerInterval);
  const el = document.getElementById('session-timer');
  if (el) el.textContent = '00:00:00';
}

// Reconciliation
function resetReconciliationPanel(disabled) {
  if (disabled) toolsSavedForSession = false;
  const card = document.getElementById('reconciliation-card');
  const saveBtn = document.getElementById('btn-save-tools');
  const checkBtn = document.getElementById('btn-check-tools');
  const badge = document.getElementById('recon-status-badge');
  if (card) card.style.display = disabled ? 'none' : 'block';
  if (saveBtn) {
    saveBtn.disabled = disabled || toolsSavedForSession;
    saveBtn.textContent = toolsSavedForSession ? 'Tools Saved' : 'Save Tools';
  }
  if (checkBtn) checkBtn.disabled = disabled;
  if (badge && !toolsSavedForSession) {
    badge.textContent = disabled ? 'No session' : 'Ready';
    badge.style.color = disabled ? 'var(--text-muted)' : 'var(--text-secondary)';
  }
  if (disabled) {
    renderReconciliationResult(null);
  }
}

async function saveTools() {
  if (!currentSession) { showToast('Start a session first', 'error'); return; }
  const saveBtn = document.getElementById('btn-save-tools');
  if (saveBtn) saveBtn.disabled = true;

  const res = await apiFetch('/api/tools/save', { method: 'POST' });
  if (!res) return;
  if (res.ok) {
    const data = await res.json();
    toolsSavedForSession = true;
    const badge = document.getElementById('recon-status-badge');
    if (badge) {
      badge.textContent = `${data.saved_tools_count} saved`;
      badge.style.color = 'var(--accent)';
    }
    setText('recon-saved-count', data.saved_tools_count);
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Tools Saved';
    }
    showToast(`Saved ${data.saved_tools_count} tool${data.saved_tools_count !== 1 ? 's' : ''}`, 'success');
    return;
  }

  const err = await res.json().catch(() => ({}));
  if (res.status === 409) {
    toolsSavedForSession = true;
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Tools Saved';
    }
  } else if (saveBtn) {
    saveBtn.disabled = false;
  }
  showToast(err.detail || 'Could not save tools', 'error');
}

async function checkTools() {
  if (!currentSession) { showToast('Start a session first', 'error'); return; }
  const checkBtn = document.getElementById('btn-check-tools');
  if (checkBtn) checkBtn.disabled = true;

  const res = await apiFetch('/api/tools/check', { method: 'POST' });
  if (!res) return;
  if (res.ok) {
    const result = await res.json();
    renderReconciliationResult(result);
    showReconciliationModal(result);
    showToast(result.message, result.safe ? 'success' : 'error');
  } else {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || 'Tool check failed', 'error');
  }
  if (checkBtn) checkBtn.disabled = false;
}

function renderReconciliationResult(result) {
  const panel = document.getElementById('recon-panel');
  if (panel) {
    panel.classList.remove('pass', 'fail');
    if (result) panel.classList.add(result.safe ? 'pass' : 'fail');
  }

  setText('recon-saved-count', result ? result.saved_tools_count : 0);
  setText('recon-current-count', result ? result.current_tools_count : 0);
  setText('recon-missing-count', result ? result.missing_tools_count : 0);
  setText('recon-checked-at', result ? new Date(result.checked_at).toLocaleTimeString() : '--');
  renderToolList('recon-missing-list', result?.missing_tools || [], 'missing');
  renderToolList('recon-present-list', result?.present_tools || [], 'present');

  const badge = document.getElementById('recon-status-badge');
  if (badge && result) {
    badge.textContent = result.status;
    badge.style.color = result.safe ? 'var(--accent)' : 'var(--danger)';
  }
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderToolList(id, tools, type) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!tools.length) {
    el.className = 'recon-list empty';
    el.textContent = type === 'missing' ? 'None' : 'No check yet';
    return;
  }
  el.className = 'recon-list';
  el.innerHTML = tools.map(name => `<span class="recon-pill ${type}">${name}</span>`).join('');
}

function showReconciliationModal(result) {
  document.getElementById('recon-modal-overlay')?.remove();
  const overlay = document.createElement('div');
  overlay.id = 'recon-modal-overlay';
  overlay.className = 'recon-alert';
  overlay.innerHTML = `
    <div class="recon-modal ${result.safe ? 'pass' : 'fail'}">
      <div class="recon-modal-title">Surgical Tool Reconciliation</div>
      <div class="recon-banner ${result.safe ? 'pass' : 'fail'}">
        ${result.safe ? 'All Surgical Tools Accounted For' : `${result.missing_tools_count} Missing Tool${result.missing_tools_count === 1 ? '' : 's'}`}
      </div>
      <div class="stat-row"><span class="stat-label">Status</span><span class="stat-value" style="color:${result.safe ? 'var(--accent)' : 'var(--danger)'}">${result.status}</span></div>
      <div class="stat-row"><span class="stat-label">Total Saved Tools</span><span class="stat-value">${result.saved_tools_count}</span></div>
      <div class="stat-row"><span class="stat-label">Total Current Tools</span><span class="stat-value">${result.current_tools_count}</span></div>
      <div class="stat-row"><span class="stat-label">Check Timestamp</span><span class="stat-value">${new Date(result.checked_at).toLocaleString()}</span></div>
      <div class="recon-list-block">
        <div class="recon-list-title">Missing Tools</div>
        <div class="recon-list ${result.missing_tools.length ? '' : 'empty'}">
          ${result.missing_tools.length ? result.missing_tools.map(name => `<span class="recon-pill missing">${name}</span>`).join('') : 'None'}
        </div>
      </div>
      <button class="btn btn-ghost w-full" style="margin-top:16px;justify-content:center" onclick="document.getElementById('recon-modal-overlay').remove()">Close</button>
    </div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

// ── History ───────────────────────────────────────────────────────
async function loadHistory() {
  const res = await apiFetch('/surgery/history');
  if (!res || !res.ok) return;
  const sessions = await res.json();
  const tbody = document.getElementById('history-tbody');
  if (!tbody) return;

  tbody.innerHTML = '';
  if (!sessions.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-muted" style="padding:20px;text-align:center">No surgery sessions yet</td></tr>`;
    return;
  }
  sessions.forEach(s => {
    const started = new Date(s.started_at).toLocaleString();
    const dur = s.duration_seconds != null
      ? `${Math.floor(s.duration_seconds / 60)}m ${s.duration_seconds % 60}s`
      : '—';
    const status = s.is_active
      ? `<span class="badge badge-surgeon">Active</span>`
      : `<span style="color:var(--text-muted)">Done</span>`;
    tbody.innerHTML += `
      <tr>
        <td>${s.or_name}</td>
        <td>${s.surgeon_name}</td>
        <td style="color:var(--text-muted)">${started}</td>
        <td style="font-family:var(--font-mono)">${dur}</td>
        <td>${status}</td>
      </tr>`;
  });
}

// ── Tool stats (historical, bottom panel) ────────────────────────
async function loadToolStats() {
  const res = await apiFetch('/tools/stats');
  if (!res || !res.ok) return;
  const stats = await res.json();
  // Target the BOTTOM panel (id="stats-history-list"), not the live panel
  const el = document.getElementById('stats-history-list');
  if (!el) return;
  if (!stats.length) {
    el.innerHTML = `<div class="stat-row"><span class="stat-label" style="color:var(--text-muted)">No data yet — start a surgery session</span></div>`;
    return;
  }
  el.innerHTML = stats.slice(0, 8).map(s =>
    `<div class="stat-row">
      <span class="stat-label">${s.name}</span>
      <span class="stat-value text-accent" title="Detected in ${s.count} frames">${s.count} frames</span>
    </div>`
  ).join('');
}

// ── Toast ─────────────────────────────────────────────────────────
function showToast(msg, type = 'success') {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = `toast ${type} show`;
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Clock ─────────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById('clock');
  if (el) el.textContent = new Date().toLocaleTimeString();
}
