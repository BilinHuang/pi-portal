/**
 * Authentication, Activation Code Redemption, User & AI Quota Admin Interactions
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

  // Admin Create User
  document.getElementById("form-create-user")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const username = document.getElementById("new-user-name").value.trim();
      const password = document.getElementById("new-user-pwd").value;
      const role = document.getElementById("new-user-role").value;
      const aiDaily = parseInt(document.getElementById("new-user-ai-daily").value, 10);
      const aiRpm = parseInt(document.getElementById("new-user-ai-rpm").value, 10);

      await API.adminCreateUser({
        username,
        password,
        role,
        ai_daily_limit: aiDaily,
        ai_rpm_limit: aiRpm,
      });

      document.getElementById("form-create-user").reset();
      document.getElementById("new-user-ai-daily").value = "50";
      document.getElementById("new-user-ai-rpm").value = "10";
      showToast(`用户 [${username}] 已创建成功`);
      await loadAdminData();
    } catch (err) {
      showToast(err.message);
    }
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
    const [users, codes, services] = await Promise.all([
      API.adminListUsers(),
      API.adminListCodes(),
      API.adminListServices(),
    ]);

    // 1. Users & AI Quota Table
    const usersBody = document.getElementById("admin-users-tbody");
    if (usersBody) {
      usersBody.innerHTML = users
        .map((u) => {
          const isUnlimited = u.ai_daily_limit === -1 || u.role === "admin";
          const quotaText = isUnlimited
            ? `👑 无限制 (${u.ai_used_today} 次已用)`
            : `${u.ai_used_today} / ${u.ai_daily_limit} 次 (今日)`;
          const roleBadge =
            u.role === "admin"
              ? `<span class="tier-badge" style="background:rgba(245,158,11,0.15);color:#fbbf24;border:1px solid rgba(245,158,11,0.3);">管理员</span>`
              : `<span class="tier-badge" style="background:rgba(56,189,248,0.15);color:#38bdf8;border:1px solid rgba(56,189,248,0.3);">普通用户</span>`;

          return `
            <tr>
              <td><strong>${Dashboard.escapeHtml(u.username)}</strong></td>
              <td>${roleBadge}</td>
              <td><code>${quotaText}</code></td>
              <td><code>${u.ai_rpm_limit} 次/分</code></td>
              <td>
                <button class="btn-action" onclick="resetUserPassword(${u.id}, '${Dashboard.escapeHtml(u.username)}')">🔑 重置密码</button>
              </td>
              <td>
                <div style="display:flex;gap:0.35rem;">
                  <button class="btn-action" onclick="editUserAiQuota(${u.id}, ${u.ai_daily_limit}, ${u.ai_rpm_limit})">⚙️ 配额</button>
                  ${
                    u.role !== "admin"
                      ? `<button class="btn-danger-sm" onclick="removeUser(${u.id}, '${Dashboard.escapeHtml(u.username)}')">删除</button>`
                      : ""
                  }
                </div>
              </td>
            </tr>
          `;
        })
        .join("");
    }

    // 2. Codes Table
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

    // 3. Services Table
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

window.resetUserPassword = async function (userId, username) {
  const newPwd = prompt(`请输入用户 [${username}] 的新密码:`);
  if (!newPwd || !newPwd.trim()) return;

  try {
    const res = await API.adminResetPassword(userId, newPwd.trim());
    showToast(res.message || "密码已重置");
  } catch (err) {
    showToast(err.message);
  }
};

window.editUserAiQuota = async function (userId, currentDaily, currentRpm) {
  const dailyStr = prompt(`设置每日 AI 调用上限次数 (-1 为无限次):`, String(currentDaily));
  if (dailyStr === null) return;
  const rpmStr = prompt(`设置每分钟请求频次上限 (RPM):`, String(currentRpm));
  if (rpmStr === null) return;

  const daily = parseInt(dailyStr, 10);
  const rpm = parseInt(rpmStr, 10);
  if (isNaN(daily) || isNaN(rpm)) {
    alert("请输入合法的数字！");
    return;
  }

  try {
    await API.adminUpdateAiQuota(userId, { ai_daily_limit: daily, ai_rpm_limit: rpm });
    showToast("AI 调用限额与频率已更新");
    await loadAdminData();
  } catch (err) {
    showToast(err.message);
  }
};

window.removeUser = async function (userId, username) {
  if (!confirm(`确定要删除用户 [${username}] 吗？此操作无法恢复。`)) return;
  try {
    await API.adminDeleteUser(userId);
    showToast(`用户 [${username}] 已删除`);
    await loadAdminData();
  } catch (err) {
    showToast(err.message);
  }
};

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
