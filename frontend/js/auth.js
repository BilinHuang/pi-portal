/**
 * Authentication, Activation Code Redemption, and Admin Modal Interactions
 */
document.addEventListener("DOMContentLoaded", () => {
  WorldClock.init();
  Dashboard.refreshAll();

  // Support URL query activation ?code=XXXX for quick guest link sharing
  const params = new URLSearchParams(window.location.search);
  const urlCode = params.get("code");
  if (urlCode) {
    window.history.replaceState({}, document.title, window.location.pathname);
    API.activateCode(urlCode)
      .then((res) => {
        showToast(res.message);
        Dashboard.refreshAll();
      })
      .catch((err) => showToast(err.message));
  }

  // Collapse/Expand Admin Switch Grid on Dashboard
  document.getElementById("btn-toggle-switch-grid")?.addEventListener("click", () => {
    document.getElementById("admin-switch-grid")?.classList.toggle("hidden");
  });

  // Modal helpers
  const openModal = (id) => document.getElementById(id)?.classList.remove("hidden");
  const closeModal = (id) => document.getElementById(id)?.classList.add("hidden");

  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.getAttribute("data-close")));
  });

  // Open Activate Modal
  document.getElementById("btn-open-activate")?.addEventListener("click", () => {
    document.getElementById("activate-feedback")?.classList.add("hidden");
    openModal("modal-activate");
    document.getElementById("input-activation-code")?.focus();
  });

  // Open Login Modal
  document.getElementById("btn-open-login")?.addEventListener("click", () => {
    document.getElementById("login-feedback")?.classList.add("hidden");
    openModal("modal-login");
    document.getElementById("input-username")?.focus();
  });

  // Open Admin Modal
  document.getElementById("btn-open-admin")?.addEventListener("click", () => {
    openModal("modal-admin");
    loadAdminData();
  });

  // Logout
  document.getElementById("btn-logout")?.addEventListener("click", async () => {
    await API.logout();
    showToast("已退出并清除当前会话权限");
    await Dashboard.refreshAll();
  });

  // Submit Activation Code
  document.getElementById("form-activate")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("input-activation-code");
    const feedback = document.getElementById("activate-feedback");
    const code = input.value.trim();
    if (!code) return;

    try {
      const res = await API.activateCode(code);
      feedback.className = "form-feedback success";
      const remainText =
        res.remaining_uses === -1
          ? "无限次有效"
          : `剩余可用次数: ${res.remaining_uses}`;
      feedback.textContent = `${res.message} (${remainText})`;
      feedback.classList.remove("hidden");
      input.value = "";
      await Dashboard.refreshAll();
      setTimeout(() => closeModal("modal-activate"), 900);
      showToast(res.message);
    } catch (err) {
      feedback.className = "form-feedback error";
      feedback.textContent = err.message;
      feedback.classList.remove("hidden");
    }
  });

  // Submit Account Login
  document.getElementById("form-login")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("input-username").value.trim();
    const password = document.getElementById("input-password").value;
    const feedback = document.getElementById("login-feedback");

    try {
      const res = await API.login(username, password);
      closeModal("modal-login");
      document.getElementById("form-login").reset();
      showToast(`欢迎回来，${res.username}！`);
      await Dashboard.refreshAll();
    } catch (err) {
      feedback.className = "form-feedback error";
      feedback.textContent = err.message;
      feedback.classList.remove("hidden");
    }
  });

  // Admin Tabs switching
  document.querySelectorAll(".admin-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".admin-tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".admin-tab-pane").forEach((p) => p.classList.add("hidden"));
      tab.classList.add("active");
      document.getElementById(tab.getAttribute("data-tab"))?.classList.remove("hidden");
    });
  });

  // Admin Create Activation Code
  document.getElementById("form-create-code")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await API.adminCreateCode({
        code: document.getElementById("new-code-str").value.trim(),
        grant_tier: document.getElementById("new-code-tier").value.trim() || null,
        grant_service_slug: document.getElementById("new-code-slug").value.trim() || null,
        max_uses: parseInt(document.getElementById("new-code-max").value, 10),
        description: document.getElementById("new-code-desc").value.trim(),
      });
      document.getElementById("form-create-code").reset();
      document.getElementById("new-code-max").value = "-1";
      showToast("激活码已创建");
      await loadAdminData();
    } catch (err) {
      showToast(err.message);
    }
  });

  // Admin Create Service
  document.getElementById("form-create-service")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await API.adminCreateService({
        slug: document.getElementById("new-svc-slug").value.trim(),
        name: document.getElementById("new-svc-name").value.trim(),
        icon: document.getElementById("new-svc-icon").value.trim() || "⚡",
        tier: document.getElementById("new-svc-tier").value,
        status: document.getElementById("new-svc-status").value,
        target_url: document.getElementById("new-svc-url").value.trim(),
        description: document.getElementById("new-svc-desc").value.trim(),
        open_in_new_tab: true,
        sort_order: 10,
      });
      document.getElementById("form-create-service").reset();
      showToast("服务卡片已添加");
      await loadAdminData();
      await Dashboard.refreshAll();
    } catch (err) {
      showToast(err.message);
    }
  });
});

async function loadAdminData() {
  try {
    const [codes, services] = await Promise.all([
      API.adminListCodes(),
      API.adminListServices(),
    ]);

    const codesBody = document.getElementById("admin-codes-tbody");
    if (codesBody) {
      codesBody.innerHTML = codes
        .map(
          (c) => `
        <tr>
          <td><code>${Dashboard.escapeHtml(c.code)}</code></td>
          <td>${Dashboard.escapeHtml(c.grant_tier || "-")}</td>
          <td>${Dashboard.escapeHtml(c.grant_service_slug || "-")}</td>
          <td>${c.used_count} / ${c.max_uses === -1 ? "∞ (无限)" : c.max_uses}</td>
          <td>${Dashboard.escapeHtml(c.description || "")}</td>
          <td>
            <button class="btn-danger-sm" onclick="removeCode(${c.id})">删除</button>
          </td>
        </tr>
      `
        )
        .join("");
    }

    const svcBody = document.getElementById("admin-services-tbody");
    if (svcBody) {
      svcBody.innerHTML = services
        .map(
          (s) => `
        <tr>
          <td>${Dashboard.escapeHtml(s.category_label)}</td>
          <td>${Dashboard.escapeHtml(s.icon)} ${Dashboard.escapeHtml(s.name)}</td>
          <td><code>${Dashboard.escapeHtml(s.slug)}</code></td>
          <td>
            <select
              onchange="Dashboard.setServiceStatus(${s.id}, this.value)"
              style="background:#0f172a;color:#e2e8f0;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:3px 6px;font-size:0.78rem;"
            >
              <option value="active" ${s.status === "active" ? "selected" : ""}>🟢 运行中</option>
              <option value="disabled" ${s.status === "disabled" ? "selected" : ""}>⚪ 已关闭</option>
              <option value="offline" ${s.status === "offline" ? "selected" : ""}>🔌 暂不可用 (Mac离线)</option>
              <option value="wip" ${s.status === "wip" ? "selected" : ""}>🚧 待开发</option>
            </select>
          </td>
          <td><code>${Dashboard.escapeHtml(s.target_url)}</code></td>
          <td>
            <button class="btn-danger-sm" onclick="removeService(${s.id})">删除</button>
          </td>
        </tr>
      `
        )
        .join("");
    }
  } catch (err) {
    showToast(err.message);
  }
}

window.removeCode = async function (id) {
  await API.adminDeleteCode(id);
  showToast("已删除激活码");
  await loadAdminData();
};

window.removeService = async function (id) {
  await API.adminDeleteService(id);
  showToast("已删除服务");
  await loadAdminData();
  await Dashboard.refreshAll();
};
