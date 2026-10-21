/**
 * Authentication, Registration, 1h Invite, Capsule Menu, and Admin Panel Interactions
 */
let questionsLoaded = false;

document.addEventListener("DOMContentLoaded", () => {
  WorldClock.init();
  Dashboard.refreshAll();

  // Support URL query activation ?code=XXXX
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

  // Collapse/Expand Admin Switch Grid
  document.getElementById("btn-toggle-switch-grid")?.addEventListener("click", () => {
    document.getElementById("admin-switch-grid")?.classList.toggle("hidden");
  });

  // Modal helpers
  const openModal = (id) => document.getElementById(id)?.classList.remove("hidden");
  const closeModal = (id) => document.getElementById(id)?.classList.add("hidden");

  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.getAttribute("data-close")));
  });

  // ==================== Top-Right User Capsule & Dropdown Menu ====================
  const capsuleBtn = document.getElementById("identity-capsule");
  const menuWrap = document.getElementById("user-menu-wrap");
  const dropdownMenu = document.getElementById("user-dropdown-menu");

  const closeDropdown = () => {
    dropdownMenu?.classList.add("hidden");
    menuWrap?.classList.remove("open");
    capsuleBtn?.setAttribute("aria-expanded", "false");
  };

  capsuleBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    const isHidden = dropdownMenu.classList.contains("hidden");
    if (isHidden) {
      dropdownMenu.classList.remove("hidden");
      menuWrap?.classList.add("open");
      capsuleBtn.setAttribute("aria-expanded", "true");
    } else {
      closeDropdown();
    }
  });

  // Close dropdown on click outside
  document.addEventListener("click", (e) => {
    if (!menuWrap?.contains(e.target)) {
      closeDropdown();
    }
  });

  // Dropdown item: 输入激活码
  document.getElementById("menu-item-activate")?.addEventListener("click", () => {
    closeDropdown();
    document.getElementById("activate-feedback")?.classList.add("hidden");
    openModal("modal-activate");
    document.getElementById("input-activation-code")?.focus();
  });

  // Dropdown item: 管理中心 (Admin)
  document.getElementById("menu-item-admin")?.addEventListener("click", () => {
    closeDropdown();
    openModal("modal-admin");
    loadAdminData();
  });

  // Dropdown item: 登录
  document.getElementById("menu-item-login")?.addEventListener("click", () => {
    closeDropdown();
    document.getElementById("login-feedback")?.classList.add("hidden");
    openModal("modal-login");
    document.getElementById("input-username")?.focus();
  });

  // Dropdown item: 注册 (访客)
  const handleOpenRegister = async () => {
    closeDropdown();
    closeModal("modal-login");
    document.getElementById("register-feedback")?.classList.add("hidden");
    openModal("modal-register");
    if (!questionsLoaded) {
      await initRegisterQuestions();
    }
    document.getElementById("reg-username")?.focus();
  };

  document.getElementById("menu-item-register")?.addEventListener("click", handleOpenRegister);
  document.getElementById("link-to-register")?.addEventListener("click", handleOpenRegister);

  // Dropdown item: 退出登录 (已登录)
  document.getElementById("menu-item-logout")?.addEventListener("click", async () => {
    closeDropdown();
    await API.logout();
    showToast("已退出登录");
    await Dashboard.refreshAll();
  });

  // ==================== Registration Questions & Form ====================

  // Dropdown selection reveals input box
  document.getElementById("reg-q1-select")?.addEventListener("change", (e) => {
    const wrap = document.getElementById("reg-q1-answer-wrap");
    const input = document.getElementById("reg-q1-answer");
    if (e.target.value) {
      wrap?.classList.remove("hidden");
      input?.focus();
    } else {
      wrap?.classList.add("hidden");
    }
  });

  document.getElementById("reg-q2-select")?.addEventListener("change", (e) => {
    const wrap = document.getElementById("reg-q2-answer-wrap");
    const input = document.getElementById("reg-q2-answer");
    if (e.target.value) {
      wrap?.classList.remove("hidden");
      input?.focus();
    } else {
      wrap?.classList.add("hidden");
    }
  });

  // Toggle bottom 1-hour invite code input
  document.getElementById("btn-toggle-reg-invite")?.addEventListener("click", () => {
    const wrap = document.getElementById("reg-invite-input-wrap");
    wrap?.classList.toggle("hidden");
    if (!wrap?.classList.contains("hidden")) {
      document.getElementById("reg-invite-code")?.focus();
    }
  });

  // Submit Registration
  document.getElementById("form-register")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const feedback = document.getElementById("register-feedback");
    const username = document.getElementById("reg-username").value.trim();
    const password = document.getElementById("reg-password").value;
    const q1_key = document.getElementById("reg-q1-select").value;
    const q1_answer = document.getElementById("reg-q1-answer").value.trim();
    const q2_key = document.getElementById("reg-q2-select").value;
    const q2_answer = document.getElementById("reg-q2-answer").value.trim();
    const invite_code = document.getElementById("reg-invite-code").value.trim();

    try {
      const res = await API.register({
        username,
        password,
        q1_key: q1_key || null,
        q1_answer: q1_answer || null,
        q2_key: q2_key || null,
        q2_answer: q2_answer || null,
        invite_code: invite_code || null,
      });
      closeModal("modal-register");
      document.getElementById("form-register").reset();
      document.getElementById("reg-q1-answer-wrap")?.classList.add("hidden");
      document.getElementById("reg-q2-answer-wrap")?.classList.add("hidden");
      document.getElementById("reg-invite-input-wrap")?.classList.add("hidden");
      showToast(`注册成功，欢迎 ${res.username}`);
      await Dashboard.refreshAll();
    } catch (err) {
      feedback.className = "form-feedback error";
      feedback.textContent = err.message;
      feedback.classList.remove("hidden");
    }
  });

  // Admin Generate 1-Hour Invite Code
  document.getElementById("btn-generate-invite")?.addEventListener("click", async () => {
    const tag = document.getElementById("invite-tag-select")?.value || "验证码";
    const tierMap = {
      初中: "6+",
      高中: "<=9+",
      大学: "<=12+",
      家人: "<=15+",
      验证码: "<=9+",
    };
    const grantTier = tierMap[tag] || "<=9+";
    try {
      const inv = await API.adminGenerateInvite(tag, grantTier);
      if (navigator.clipboard) {
        navigator.clipboard.writeText(inv.code).catch(() => {});
      }
      showToast(`已生成临时码: ${inv.code} (已复制)`);
      await loadAdminData();
    } catch (err) {
      showToast(err.message);
    }
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
          ? "无限次"
          : `剩余 ${res.remaining_uses} 次`;
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

  // Submit Login
  document.getElementById("form-login")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("input-username").value.trim();
    const password = document.getElementById("input-password").value;
    const feedback = document.getElementById("login-feedback");

    try {
      const res = await API.login(username, password);
      closeModal("modal-login");
      document.getElementById("form-login").reset();
      showToast(`登录成功`);
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
      const user_tag = document.getElementById("new-user-tag").value;
      const role = document.getElementById("new-user-role").value;
      const aiDaily = parseInt(document.getElementById("new-user-ai-daily").value, 10);
      const aiRpm = parseInt(document.getElementById("new-user-ai-rpm").value, 10);

      await API.adminCreateUser({
        username,
        password,
        role,
        user_tag,
        ai_daily_limit: aiDaily,
        ai_rpm_limit: aiRpm,
      });

      document.getElementById("form-create-user").reset();
      document.getElementById("new-user-ai-daily").value = "50";
      document.getElementById("new-user-ai-rpm").value = "10";
      showToast(`用户 [${username}] 已创建`);
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
      const sortVal = parseInt(document.getElementById("new-svc-order")?.value || "1", 10);
      await API.adminCreateService({
        slug: document.getElementById("new-svc-slug").value.trim(),
        name: document.getElementById("new-svc-name").value.trim(),
        icon: document.getElementById("new-svc-icon").value.trim() || "⚡",
        tier: document.getElementById("new-svc-tier").value,
        status: document.getElementById("new-svc-status").value,
        target_url: document.getElementById("new-svc-url").value.trim(),
        description: document.getElementById("new-svc-desc").value.trim(),
        open_in_new_tab: true,
        sort_order: isNaN(sortVal) ? 1 : sortVal,
      });
      document.getElementById("form-create-service").reset();
      showToast("服务已添加");
      await loadAdminData();
      await Dashboard.refreshAll();
    } catch (err) {
      showToast(err.message);
    }
  });
});

async function initRegisterQuestions() {
  try {
    const data = await API.getRegisterQuestions();
    const s1 = document.getElementById("reg-q1-select");
    const s2 = document.getElementById("reg-q2-select");
    if (s1 && Array.isArray(data.identity_questions)) {
      s1.innerHTML =
        `<option value="">-- 选择问题一 --</option>` +
        data.identity_questions
          .map((q) => `<option value="${Dashboard.escapeHtml(q.key)}">${Dashboard.escapeHtml(q.prompt)}</option>`)
          .join("");
    }
    if (s2 && Array.isArray(data.life_questions)) {
      s2.innerHTML =
        `<option value="">-- 选择问题二 --</option>` +
        data.life_questions
          .map((q) => `<option value="${Dashboard.escapeHtml(q.key)}">${Dashboard.escapeHtml(q.prompt)}</option>`)
          .join("");
    }
    questionsLoaded = true;
  } catch (err) {
    console.error("Failed to load register questions:", err);
  }
}

function getCircleBadgeHtml(tag) {
  const map = {
    初中: "circle-junior",
    高中: "circle-senior",
    大学: "circle-uni",
    家人: "circle-family",
  };
  const cls = map[tag] || "circle-default";
  return `<span class="circle-badge ${cls}">${Dashboard.escapeHtml(tag || "普通")}</span>`;
}

async function loadAdminData() {
  try {
    const [users, invites, codes, services] = await Promise.all([
      API.adminListUsers(),
      API.adminListInvites(),
      API.adminListCodes(),
      API.adminListServices(),
    ]);

    // 0. Render 1-Hour Registration Invites Strip
    const invList = document.getElementById("admin-invites-list");
    if (invList) {
      if (invites.length === 0) {
        invList.innerHTML = "";
      } else {
        invList.innerHTML = invites
          .map((inv) => {
            const expTime = new Date(inv.expires_at).toLocaleTimeString("zh-CN", {
              hour: "2-digit",
              minute: "2-digit",
            });
            let stateBadge = `<span style="color:#34d399;">${expTime} 到期</span>`;
            if (inv.is_used) {
              stateBadge = `<span style="color:#94a3b8;">已用 (${Dashboard.escapeHtml(inv.used_by || "")})</span>`;
            } else if (inv.is_expired) {
              stateBadge = `<span style="color:#f43f5e;">已过期</span>`;
            }
            return `
              <div class="invite-pill ${inv.is_used || inv.is_expired ? "expired" : ""}">
                <code><strong>${Dashboard.escapeHtml(inv.code)}</strong></code>
                <span>[${Dashboard.escapeHtml(inv.user_tag)}]</span>
                ${stateBadge}
                <button class="btn-action" onclick="copyText('${Dashboard.escapeHtml(inv.code)}')">复制</button>
                <button class="btn-action" style="color:#fb7185;" onclick="removeInvite(${inv.id})">✕</button>
              </div>
            `;
          })
          .join("");
      }
    }

    // 1. Users, Passwords & AI Quota Table
    const usersBody = document.getElementById("admin-users-tbody");
    if (usersBody) {
      usersBody.innerHTML = users
        .map((u) => {
          const isUnlimited = u.ai_daily_limit === -1 || u.role === "admin";
          const quotaText = isUnlimited
            ? `无限 (${u.ai_used_today} 次)`
            : `${u.ai_used_today} / ${u.ai_daily_limit} 次`;
          const roleBadge =
            u.role === "admin"
              ? `<span class="circle-badge" style="background:rgba(245,158,11,0.15);color:#fbbf24;border:1px solid rgba(245,158,11,0.3);">管理员</span>`
              : `<span style="color:var(--text-muted);font-size:0.78rem;">用户</span>`;
          const pwdVal = u.password_plain || "-";

          return `
            <tr>
              <td><strong>${Dashboard.escapeHtml(u.username)}</strong></td>
              <td>${getCircleBadgeHtml(u.user_tag)}</td>
              <td>${roleBadge}</td>
              <td>
                <div style="display:flex;align-items:center;gap:0.35rem;">
                  <code id="pwd-mask-${u.id}" data-plain="${Dashboard.escapeHtml(pwdVal)}" data-shown="0">••••••</code>
                  <button class="btn-action" onclick="toggleShowPwd(${u.id})">👁️</button>
                  <button class="btn-action" onclick="resetUserPassword(${u.id}, '${Dashboard.escapeHtml(u.username)}')">改密</button>
                </div>
              </td>
              <td><code>${quotaText}</code></td>
              <td><code>${u.ai_rpm_limit} /分</code></td>
              <td>
                <div style="display:flex;gap:0.35rem;">
                  <button class="btn-action" onclick="editUserAiQuota(${u.id}, ${u.ai_daily_limit}, ${u.ai_rpm_limit}, '${Dashboard.escapeHtml(u.user_tag)}')">设置</button>
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
          <td>${c.used_count} / ${c.max_uses === -1 ? "无限" : c.max_uses}</td>
          <td>${Dashboard.escapeHtml(c.description || "")}</td>
          <td>
            <button class="btn-danger-sm" onclick="removeCode(${c.id})">删除</button>
          </td>
        </tr>
      `
        )
        .join("");
    }

    // 3. Services Table (with editable Tier & Position Order)
    const svcBody = document.getElementById("admin-services-tbody");
    if (svcBody) {
      svcBody.innerHTML = services
        .map(
          (s) => `
        <tr>
          <td>
            <select
              onchange="Dashboard.setServicePlacement(${s.id}, { tier: this.value })"
              style="background:#0f172a;color:#38bdf8;border:1px solid rgba(56,189,248,0.28);border-radius:6px;padding:3px 6px;font-size:0.78rem;font-weight:600;"
            >
              <option value="6+" ${s.tier === "6+" ? "selected" : ""}>公共基础 (6+)</option>
              <option value="9+" ${s.tier === "9+" ? "selected" : ""}>家庭共享 (9+)</option>
              <option value="12+" ${s.tier === "12+" ? "selected" : ""}>云端开发 (12+)</option>
              <option value="15+" ${s.tier === "15+" ? "selected" : ""}>核心网络 (15+)</option>
              <option value="18+" ${s.tier === "18+" ? "selected" : ""}>私密专区 (18+)</option>
            </select>
          </td>
          <td>
            <div style="display:flex;align-items:center;gap:0.25rem;">
              <button class="btn-action" title="前移" onclick="Dashboard.setServicePlacement(${s.id}, { direction: 'up' })">↑</button>
              <input
                type="number"
                value="${s.sort_order}"
                min="0"
                max="999"
                onchange="Dashboard.setServicePlacement(${s.id}, { sort_order: parseInt(this.value, 10) || 0 })"
                style="width:48px;background:#0f172a;color:#e2e8f0;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:2px 5px;font-size:0.78rem;text-align:center;"
              />
              <button class="btn-action" title="后移" onclick="Dashboard.setServicePlacement(${s.id}, { direction: 'down' })">↓</button>
            </div>
          </td>
          <td>${Dashboard.escapeHtml(s.icon)} ${Dashboard.escapeHtml(s.name)}</td>
          <td><code>${Dashboard.escapeHtml(s.slug)}</code></td>
          <td>
            <select
              onchange="Dashboard.setServiceStatus(${s.id}, this.value)"
              style="background:#0f172a;color:#e2e8f0;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:3px 6px;font-size:0.78rem;"
            >
              <option value="active" ${s.status === "active" ? "selected" : ""}>运行中</option>
              <option value="disabled" ${s.status === "disabled" ? "selected" : ""}>已关闭</option>
              <option value="offline" ${s.status === "offline" ? "selected" : ""}>暂不可用</option>
              <option value="wip" ${s.status === "wip" ? "selected" : ""}>待开发</option>
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

window.toggleShowPwd = function (userId) {
  const el = document.getElementById(`pwd-mask-${userId}`);
  if (!el) return;
  const isShown = el.getAttribute("data-shown") === "1";
  if (isShown) {
    el.textContent = "••••••";
    el.setAttribute("data-shown", "0");
  } else {
    el.textContent = el.getAttribute("data-plain") || "";
    el.setAttribute("data-shown", "1");
  }
};

window.copyText = function (txt) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(txt);
    showToast(`已复制: ${txt}`);
  }
};

window.removeInvite = async function (inviteId) {
  await API.adminDeleteInvite(inviteId);
  await loadAdminData();
};

window.resetUserPassword = async function (userId, username) {
  const newPwd = prompt(`设置用户 [${username}] 的新密码:`);
  if (!newPwd || !newPwd.trim()) return;

  try {
    const res = await API.adminResetPassword(userId, newPwd.trim());
    showToast(res.message || "密码已更新");
    await loadAdminData();
  } catch (err) {
    showToast(err.message);
  }
};

window.editUserAiQuota = async function (userId, currentDaily, currentRpm, currentTag) {
  const tagStr = prompt(`设置分类 (初中/高中/大学/家人/普通):`, currentTag || "普通");
  if (tagStr === null) return;
  const dailyStr = prompt(`每日 AI 配额 (-1 为无限):`, String(currentDaily));
  if (dailyStr === null) return;
  const rpmStr = prompt(`每分钟频次 (RPM):`, String(currentRpm));
  if (rpmStr === null) return;

  const daily = parseInt(dailyStr, 10);
  const rpm = parseInt(rpmStr, 10);
  if (isNaN(daily) || isNaN(rpm)) {
    alert("请输入数字");
    return;
  }

  try {
    await API.adminUpdateAiQuota(userId, {
      user_tag: tagStr.trim() || "普通",
      ai_daily_limit: daily,
      ai_rpm_limit: rpm,
    });
    showToast("已更新设置");
    await loadAdminData();
  } catch (err) {
    showToast(err.message);
  }
};

window.removeUser = async function (userId, username) {
  if (!confirm(`确定删除用户 [${username}] 吗？`)) return;
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
