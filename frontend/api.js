// =============================================================================
// api.js  –  Shared API client for AttendTrax frontend
// =============================================================================

// ── API Base URL Resolution (Localhost, file://, and Cloud) ────────────────
const CLOUD_API = 'https://attendtrax-api.onrender.com';
const LOCAL_API = 'http://127.0.0.1:8000';

const isLocalEnv = window.location.hostname === 'localhost'
  || window.location.hostname === '127.0.0.1'
  || window.location.hostname === ''
  || window.location.protocol === 'file:';

// Default to Cloud API unless explicitly configured to local or local probe succeeds
let API_BASE = (isLocalEnv && localStorage.getItem('at_api_env') === 'local')
  ? LOCAL_API
  : CLOUD_API;

window.API_BASE = API_BASE;
window.setApiEnv = (env) => {
  if (env === 'local') {
    API_BASE = LOCAL_API;
    localStorage.setItem('at_api_env', 'local');
  } else {
    API_BASE = CLOUD_API;
    localStorage.setItem('at_api_env', 'cloud');
  }
  window.API_BASE = API_BASE;
  console.log('[AttendTrax API] Environment switched to:', API_BASE);
};

// ── Token storage ──────────────────────────────────────────────────────────
function saveAuth(data) {
  localStorage.setItem('at_token', data.access_token);
  localStorage.setItem('at_role',  data.role);
  localStorage.setItem('at_name',  data.name);
  localStorage.setItem('at_uid',   data.user_id);
  localStorage.setItem('at_class', data.class_id || '');
  if (data.username) {
    localStorage.setItem('at_username', data.username);
  } else if (data.access_token) {
    try {
      const payload = JSON.parse(atob(data.access_token.split('.')[1]));
      if (payload && payload.sub) {
        localStorage.setItem('at_username', payload.sub);
      }
    } catch (e) {}
  }
}

function getToken()   { return localStorage.getItem('at_token'); }
function getRole()    { return localStorage.getItem('at_role'); }
function getName()    { return localStorage.getItem('at_name'); }
function getUserId()  { return localStorage.getItem('at_uid'); }
function getClassId() { return localStorage.getItem('at_class'); }
function getUsername() {
  const stored = localStorage.getItem('at_username');
  if (stored) return stored;
  const token = getToken();
  if (token) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload && payload.sub) return payload.sub;
    } catch (e) {}
  }
  return '';
}

function clearAuth() {
  ['at_token','at_role','at_name','at_uid','at_class','at_username'].forEach(k => localStorage.removeItem(k));
}

// Explicit window bindings for cross-script safety
window.saveAuth = saveAuth;
window.getToken = getToken;
window.getRole = getRole;
window.getName = getName;
window.getUserId = getUserId;
window.getClassId = getClassId;
window.getUsername = getUsername;
window.clearAuth = clearAuth;

// ── Proactive Server Pre-warm & Warmup Telemetry ───────────────────────────
let _warmupPillEl = null;
let _warmupDismissTimer = null;

function showWarmupPill(show, text = 'Connecting to live server…') {
  if (typeof document === 'undefined') return;
  if (!_warmupPillEl) {
    _warmupPillEl = document.createElement('div');
    _warmupPillEl.id = 'server-warmup-pill';
    _warmupPillEl.className = 'server-warmup-pill';
    _warmupPillEl.innerHTML = `
      <span class="warmup-spinner"></span>
      <span class="warmup-text">${text}</span>
    `;
    document.body.appendChild(_warmupPillEl);
  }
  clearTimeout(_warmupDismissTimer);
  if (show) {
    _warmupPillEl.querySelector('.warmup-text').textContent = text;
    _warmupPillEl.classList.add('visible');
    // Auto-dismiss warmup notification after 3.5 seconds
    _warmupDismissTimer = setTimeout(() => {
      if (_warmupPillEl) _warmupPillEl.classList.remove('visible');
    }, 3500);
  } else {
    _warmupPillEl.classList.remove('visible');
  }
}

// Proactively ping server in background on script execution
function warmupServer() {
  try {
    fetch(`${API_BASE}/`, { method: 'GET', mode: 'cors' }).catch(() => {});
  } catch (e) {}
}
warmupServer();

// ── Performance Utilities: Debounce & Throttle ─────────────────────────────
function debounce(fn, delay = 250) {
  let timer = null;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}
window.debounce = debounce;

function throttle(fn, limit = 250) {
  let inThrottle = false;
  return function (...args) {
    if (!inThrottle) {
      fn.apply(this, args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}
window.throttle = throttle;

// ── In-memory Client Cache & SWR (Stale-While-Revalidate) ────────────────────
const _apiCache = new Map();
const DEFAULT_CACHE_TTL = 30000; // 30 seconds default for static metadata

function clearClientCache() {
  _apiCache.clear();
}

// ── Core fetch wrapper with Cold-Start Resilience, Retries & SWR ────────────
async function apiFetch(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const isGet = method === 'GET';
  
  // Real-time bypass condition (attendance check or explicit bypassCache)
  const isStrictRealTime = path.includes('/attendance/check') || options.bypassCache === true;
  const ttl = options.ttl || (path.includes('/analytics') || path.includes('/reports') ? 15000 : DEFAULT_CACHE_TTL);

  if (isGet && !isStrictRealTime) {
    const cached = _apiCache.get(path);
    if (cached) {
      const isFresh = (Date.now() - cached.ts) < ttl;
      if (isFresh) {
        return cached.data;
      }
      // SWR pattern: return stale immediately and revalidate asynchronously
      if (options.swr) {
        apiFetch(path, { ...options, swr: false, bypassCache: true })
          .then(fresh => {
            if (typeof options.onFresh === 'function') {
              options.onFresh(fresh);
            }
          })
          .catch(() => {});
        return cached.data;
      }
    }
  }

  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  // Start background warm-up indicator if request takes > 1.8s
  const warmupTimer = setTimeout(() => {
    showWarmupPill(true, 'Connecting to live cloud backend… Please hold on a moment.');
  }, 1800);

  let res;
  let lastErr = null;
  const maxAttempts = 5;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers,
      });
      if (res) break;
    } catch (netErr) {
      lastErr = netErr;
      // If localhost failed in local environment, auto-switch to Render cloud API and retry immediately
      if (API_BASE === LOCAL_API) {
        console.warn('[AttendTrax API] Localhost unreachable. Falling back to live Render Cloud API...');
        API_BASE = CLOUD_API;
        window.API_BASE = CLOUD_API;
        continue;
      }
      if (attempt < maxAttempts - 1) {
        const delay = Math.min(1200 * Math.pow(1.5, attempt), 8000);
        showWarmupPill(true, `Waking up cloud backend (Attempt ${attempt + 2}/${maxAttempts})…`);
        await new Promise(r => setTimeout(r, delay));
      }
    }
  }

  clearTimeout(warmupTimer);
  showWarmupPill(false);

  if (!res) {
    throw new Error('Unable to connect to live server. The cloud service may be waking up or your internet connection is offline. Please retry in a moment.');
  }

  if (res.status === 401 && !path.includes('/auth/login')) {
    clearAuth();
    clearClientCache();
    window.location.href = 'index.html';
    throw new Error('Session expired. Please login again.');
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const rawMsg = data?.detail || data?.message || `Error ${res.status}`;
    const msg = typeof rawMsg === 'string'
      ? rawMsg
      : (Array.isArray(rawMsg) ? rawMsg.map(e => e.msg || JSON.stringify(e)).join(', ') : JSON.stringify(rawMsg));
    throw new Error(msg);
  }

  if (isGet) {
    _apiCache.set(path, { ts: Date.now(), data });
  } else {
    clearClientCache();
  }

  return data;
}

// ── Convenience methods ────────────────────────────────────────────────────
const api = {
  post:      (path, body)                 => { clearClientCache(); return apiFetch(path, { method: 'POST',   body: JSON.stringify(body) }); },
  get:       (path, opts)                 => apiFetch(path, { method: 'GET', ...opts }),
  cachedGet: (path, ttl = 30000, opts = {}) => apiFetch(path, { method: 'GET', ttl, ...opts }),
  swrGet:    (path, onFresh, opts = {})   => apiFetch(path, { method: 'GET', swr: true, onFresh, ...opts }),
  patch:     (path, body)                 => { clearClientCache(); return apiFetch(path, { method: 'PATCH',  body: JSON.stringify(body) }); },
  delete:    (path)                       => { clearClientCache(); return apiFetch(path, { method: 'DELETE' }); },
  upload:    async (path, formData)      => {
    clearClientCache();
    const token = getToken();
    let targetBase = API_BASE;
    let r;
    try {
      r = await fetch(`${targetBase}${path}`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
    } catch (e) {
      if (targetBase === LOCAL_API) {
        targetBase = CLOUD_API;
        API_BASE = CLOUD_API;
        r = await fetch(`${targetBase}${path}`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
        });
      } else {
        throw new Error('Upload failed: unable to connect to server. Please check your network.');
      }
    }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      const rawMsg = d?.detail || d?.message || `Error ${r.status}`;
      const msg = typeof rawMsg === 'string'
        ? rawMsg
        : (Array.isArray(rawMsg) ? rawMsg.map(e => e.msg || JSON.stringify(e)).join(', ') : JSON.stringify(rawMsg));
      throw new Error(msg);
    }
    return d;
  },
  clearCache: clearClientCache,
};

// ── Toast notifications ────────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const icons = {
    success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    error: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  };
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span class="toast-icon" style="display:inline-flex;align-items:center;">${icons[type] || icons.info}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('leaving');
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ── Loader with Safety Auto-Dismiss ───────────────────────────────────────
let _pageLoaderTimer = null;
function showLoader(show) {
  const el = document.getElementById('page-loader');
  if (!el) return;
  clearTimeout(_pageLoaderTimer);
  if (show) {
    el.classList.remove('hidden');
    // Safety auto-dismiss after 2.5s so user is never locked out
    _pageLoaderTimer = setTimeout(() => {
      el.classList.add('hidden');
    }, 2500);
  } else {
    el.classList.add('hidden');
  }
}
window.showLoader = showLoader;

// Proactively dismiss loader when DOM is ready
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => showLoader(false), 200);
  });
  window.addEventListener('load', () => {
    setTimeout(() => showLoader(false), 50);
  });
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

// ── XSS Sanitizer ──────────────────────────────────────────────────────────
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
window.escapeHtml = escapeHtml;

function requireAuth(expectedRole) {
  const token = getToken();
  const role  = (getRole() || '').toUpperCase();
  if (!token || !role) {
    window.location.href = 'index.html';
    return false;
  }
  if (expectedRole) {
    const exp = expectedRole.toUpperCase();
    let isAllowed = false;
    if (exp === 'ADMIN' && (role === 'ADMIN' || role === 'SUPER_ADMIN' || role === 'DEPT_ADMIN' || role === 'WARDEN')) {
      isAllowed = true;
    } else if (exp === 'FACULTY' && (role === 'FACULTY' || role === 'CLASS_INCHARGE' || role === 'DEPT_ADMIN' || role === 'ADMIN' || role === 'SUPER_ADMIN')) {
      isAllowed = true;
    } else if (exp === 'STUDENT' && role === 'STUDENT') {
      isAllowed = true;
    } else if (exp === role) {
      isAllowed = true;
    }

    if (!isAllowed) {
      const pages = { 
        SUPER_ADMIN: 'admin.html', 
        DEPT_ADMIN: 'admin.html', 
        ADMIN: 'admin.html', 
        WARDEN: 'gatepass.html',
        FACULTY: 'faculty.html', 
        CLASS_INCHARGE: 'faculty.html', 
        STUDENT: 'student.html' 
      };
      window.location.href = pages[role] || 'index.html';
      return false;
    }
  }
  return true;
}
