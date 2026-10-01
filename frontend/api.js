// =============================================================================
// api.js  –  Shared API client for AttendTrax frontend
// =============================================================================

// ── CHANGE this to your Render backend URL after deployment ────────────────
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://127.0.0.1:8000'
  : 'https://attendtrax-api.onrender.com';   // ← update after Render deploy

// ── Token storage ──────────────────────────────────────────────────────────
function saveAuth(data) {
  localStorage.setItem('at_token', data.access_token);
  localStorage.setItem('at_role',  data.role);
  localStorage.setItem('at_name',  data.name);
  localStorage.setItem('at_uid',   data.user_id);
  localStorage.setItem('at_class', data.class_id || '');
}

function getToken()   { return localStorage.getItem('at_token'); }
function getRole()    { return localStorage.getItem('at_role'); }
function getName()    { return localStorage.getItem('at_name'); }
function getUserId()  { return localStorage.getItem('at_uid'); }
function getClassId() { return localStorage.getItem('at_class'); }

function clearAuth() {
  ['at_token','at_role','at_name','at_uid','at_class'].forEach(k => localStorage.removeItem(k));
}

// ── Core fetch wrapper ─────────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    clearAuth();
    window.location.href = 'index.html';
    throw new Error('Session expired. Please login again.');
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const msg = data?.detail || data?.message || `Error ${res.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }

  return data;
}

// ── Convenience methods ────────────────────────────────────────────────────
const api = {
  post:   (path, body)        => apiFetch(path, { method: 'POST',   body: JSON.stringify(body) }),
  get:    (path)              => apiFetch(path, { method: 'GET' }),
  patch:  (path, body)        => apiFetch(path, { method: 'PATCH',  body: JSON.stringify(body) }),
  delete: (path)              => apiFetch(path, { method: 'DELETE' }),
  upload: (path, formData)    => fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken()}` },
    body: formData,
  }).then(async r => {
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d?.detail || `Error ${r.status}`);
    return d;
  }),
};

// ── Toast notifications ────────────────────────────────────────────────────
const _toastIcons = {
  success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  error:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  info:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
  warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
};
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span class="toast-icon-wrap">${_toastIcons[type] || _toastIcons.info}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('leaving');
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ── Loader ─────────────────────────────────────────────────────────────────
function showLoader(show) {
  const el = document.getElementById('page-loader');
  if (el) el.classList.toggle('hidden', !show);
}

// ── Date helpers ───────────────────────────────────────────────────────────
function todayDisplay() {
  return new Date().toLocaleDateString('en-IN', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
  });
}

function todayShort() {
  const d = new Date();
  const dd = String(d.getDate()).padStart(2,'0');
  const mm = String(d.getMonth()+1).padStart(2,'0');
  const yyyy = d.getFullYear();
  return `${dd}-${mm}-${yyyy}`;
}

// ── Auth guard (call on every protected page) ──────────────────────────────
function requireAuth(expectedRole) {
  const token = getToken();
  const role  = getRole();
  if (!token || !role) {
    window.location.href = 'index.html';
    return false;
  }
  if (expectedRole && role.toUpperCase() !== expectedRole.toUpperCase()) {
    // Wrong role – redirect to correct page
    const pages = { ADMIN: 'admin.html', FACULTY: 'faculty.html', STUDENT: 'student.html' };
    window.location.href = pages[role.toUpperCase()] || 'index.html';
    return false;
  }
  return true;
}
