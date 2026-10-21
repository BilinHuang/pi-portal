/**
 * API helper wrapper for Pi Stealth Portal
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

  getRegisterQuestions() {
    return this.request("/api/auth/register-questions");
  },

  register(payload) {
    return this.request("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
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

  getAiQuota() {
    return this.request("/api/ai/quota");
  },

  consumeAiQuota() {
    return this.request("/api/ai/consume", {
      method: "POST",
    });
  },

  // Admin APIs (return 404 unless logged in as admin)
  adminListUsers() {
    return this.request("/api/admin/users");
  },

  adminCreateUser(payload) {
    return this.request("/api/admin/users", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  adminResetPassword(userId, new_password) {
    return this.request(`/api/admin/users/${userId}/password`, {
      method: "PUT",
      body: JSON.stringify({ new_password }),
    });
  },

  adminUpdateAiQuota(userId, payload) {
    return this.request(`/api/admin/users/${userId}/ai-quota`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  adminDeleteUser(userId) {
    return this.request(`/api/admin/users/${userId}`, {
      method: "DELETE",
    });
  },

  adminListInvites() {
    return this.request("/api/admin/invites");
  },

  adminGenerateInvite(user_tag = "验证码", grant_tier = "<=9+") {
    return this.request(
      `/api/admin/invites?user_tag=${encodeURIComponent(user_tag)}&grant_tier=${encodeURIComponent(grant_tier)}`,
      { method: "POST" }
    );
  },

  adminDeleteInvite(inviteId) {
    return this.request(`/api/admin/invites/${inviteId}`, {
      method: "DELETE",
    });
  },

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

  adminUpdateServicePlacement(id, payload) {
    return this.request(`/api/admin/services/${id}/placement`, {
      method: "PATCH",
      body: JSON.stringify(payload),
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
