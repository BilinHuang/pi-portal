/**
 * API helper wrapper for Pi Stealth Dashboard
 */
const API = {
  async request(url, options = {}) {
    const config = {
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(options.headers || {}),
      },
      ...options,
    };

    const response = await fetch(url, config);
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || `请求失败 (${response.status})`);
    }
    return data;
  },

  getMe() {
    return this.request("/api/auth/me");
  },

  login(username, password) {
    return this.request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  },

  activateCode(code) {
    return this.request("/api/auth/activate", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
  },

  logout() {
    return this.request("/api/auth/logout", {
      method: "POST",
    });
  },

  getServices() {
    return this.request("/api/services");
  },

  getTimezones() {
    return this.request("/api/widgets/timezones");
  },

  getSystemStatus() {
    return this.request("/api/widgets/system");
  },

  // Admin APIs (return 404 unless logged in as admin)
  adminListCodes() {
    return this.request("/api/admin/codes");
  },

  adminCreateCode(payload) {
    return this.request("/api/admin/codes", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  adminDeleteCode(id) {
    return this.request(`/api/admin/codes/${id}`, {
      method: "DELETE",
    });
  },

  adminListServices() {
    return this.request("/api/admin/services");
  },

  adminUpdateServiceStatus(id, status) {
    return this.request(`/api/admin/services/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
  },

  adminCreateService(payload) {
    return this.request("/api/admin/services", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  adminDeleteService(id) {
    return this.request(`/api/admin/services/${id}`, {
      method: "DELETE",
    });
  },
};

function showToast(message, duration = 3200) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => {
    el.classList.add("hidden");
  }, duration);
}
