/**
 * Stealth Dashboard Service Matrix & Admin Feature Switch Renderer
 * - Never displays explicit age ratings (6+, 9+, 12+, 15+, 18+) on the UI.
 * - Replaces the top-right card badge with operational status tags:
 *   '运行中' (green) vs grey tags for '已关闭', '暂不可用' (e.g. Mac offline), and '待开发'.
 * - Renders the Feature Switch Control Panel ONLY when logged in as admin.
 */
const Dashboard = {
  isAdmin: false,

  async refreshAll() {
    await this.loadIdentity();
    const tasks = [this.loadServices()];
    if (this.isAdmin) {
      tasks.push(this.loadAdminSwitchPanel());
    }
    await Promise.all(tasks);
  },

  async loadIdentity() {
    try {
      const auth = await API.getMe();
      this.isAdmin = auth.role === "admin";

      const nameEl = document.getElementById("identity-name");
      const btnLogin = document.getElementById("btn-open-login");
      const btnLogout = document.getElementById("btn-logout");
      const btnAdmin = document.getElementById("btn-open-admin");
      const adminSwitchPanel = document.getElementById("admin-switch-panel");
      const footerIp = document.getElementById("footer-ip");

      if (footerIp && auth.client_ip) {
        footerIp.textContent = `IP: ${auth.client_ip}`;
      }

      if (auth.is_authenticated) {
        nameEl.textContent =
          auth.role === "admin"
            ? `👑 管理员 (${auth.username})`
            : `👤 已登录 (${auth.username})`;
        btnLogin.classList.add("hidden");
        btnLogout.classList.remove("hidden");
      } else if (auth.is_guest_activated) {
        nameEl.textContent = "🎟️ 已授权访问";
        btnLogin.classList.remove("hidden");
        btnLogout.classList.remove("hidden");
      } else {
        nameEl.textContent = "访客模式";
        btnLogin.classList.remove("hidden");
        btnLogout.classList.add("hidden");
      }

      if (this.isAdmin) {
        btnAdmin.classList.remove("hidden");
        adminSwitchPanel?.classList.remove("hidden");
      } else {
        btnAdmin.classList.add("hidden");
        adminSwitchPanel?.classList.add("hidden");
      }
    } catch (err) {
      console.error("Failed to load identity:", err);
    }
  },

  async loadAdminSwitchPanel() {
    const grid = document.getElementById("admin-switch-grid");
    if (!grid || !this.isAdmin) return;

    try {
      const services = await API.adminListServices();
      const states = [
        { key: "active", label: "开启" },
        { key: "disabled", label: "已关闭" },
        { key: "offline", label: "暂不可用" },
        { key: "wip", label: "待开发" },
      ];

      grid.innerHTML = services
        .map(
          (svc) => `
        <div class="switch-item">
          <div class="switch-item-top">
            <span class="switch-item-name">
              <span>${this.escapeHtml(svc.icon)}</span>
              <span>${this.escapeHtml(svc.name)}</span>
            </span>
            <span class="switch-item-group">${this.escapeHtml(svc.category_label)}</span>
          </div>
          <div class="state-segmented">
            ${states
              .map(
                (st) => `
              <button
                type="button"
                class="state-btn ${svc.status === st.key ? `active-state-${st.key}` : ""}"
                onclick="Dashboard.setServiceStatus(${svc.id}, '${st.key}')"
              >
                ${st.label}
              </button>
            `
              )
              .join("")}
          </div>
        </div>
      `
        )
        .join("");
    } catch (err) {
      console.error("Failed to load admin switch panel:", err);
    }
  },

  async setServiceStatus(serviceId, newStatus) {
    try {
      const res = await API.adminUpdateServiceStatus(serviceId, newStatus);
      showToast(`已将服务状态切换为「${res.status_label}」`);
      await Promise.all([
        this.loadAdminSwitchPanel(),
        this.loadServices(),
      ]);
      if (typeof loadAdminData === "function") {
        const adminModal = document.getElementById("modal-admin");
        if (adminModal && !adminModal.classList.contains("hidden")) {
          await loadAdminData();
        }
      }
    } catch (err) {
      showToast(err.message);
    }
  },

  async loadServices() {
    const container = document.getElementById("services-container");
    if (!container) return;

    try {
      const data = await API.getServices();
      const groups = data.groups || [];

      if (groups.length === 0) {
        container.innerHTML = "";
        return;
      }

      container.innerHTML = groups
        .map(
          (group) => `
        <section class="tier-section" data-group="${this.escapeHtml(group.group_id)}">
          <div class="tier-header">
            <h2 class="tier-title">${this.escapeHtml(group.label)}</h2>
            <span class="tier-subtitle">${this.escapeHtml(group.subtitle)}</span>
          </div>
          <div class="service-grid">
            ${group.services.map((svc) => this.renderServiceCard(svc)).join("")}
          </div>
        </section>
      `
        )
        .join("");
    } catch (err) {
      console.error("Failed to load services:", err);
    }
  },

  renderServiceCard(svc) {
    const isAvailable = Boolean(svc.is_available);
    const unavailableClass = isAvailable ? "" : "service-card-unavailable";
    const hrefAttr = isAvailable
      ? `href="${this.escapeHtml(svc.launch_url)}" ${
          svc.open_in_new_tab ? 'target="_blank" rel="noopener noreferrer"' : ""
        }`
      : `href="javascript:void(0)" onclick="Dashboard.notifyUnavailable('${this.escapeHtml(
          svc.name
        )}', '${this.escapeHtml(svc.status_label)}')"`;

    return `
      <a class="service-card ${unavailableClass}" ${hrefAttr}>
        <div class="service-icon">${this.escapeHtml(svc.icon)}</div>
        <div class="service-info">
          <div class="service-title-row">
            <span class="service-name">${this.escapeHtml(svc.name)}</span>
            <span class="status-tag ${this.escapeHtml(svc.status_badge_class)}">
              ${this.escapeHtml(svc.status_label)}
            </span>
          </div>
          <p class="service-desc">${this.escapeHtml(svc.description)}</p>
        </div>
      </a>
    `;
  },

  notifyUnavailable(name, statusLabel) {
    showToast(`「${name}」当前状态为【${statusLabel}】，暂无法访问`);
  },

  escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  },
};
