/**
 * Multi-Timezone World Clock Widget (Default: Shanghai, Tokyo, Sydney)
 * Synchronizes metadata with server and ticks smoothly every second on the client.
 */
const WorldClock = {
  zones: [
    { id: "shanghai", city: "上海", country: "CN", timezone: "Asia/Shanghai", utc_offset: "UTC+8" },
    { id: "tokyo", city: "东京", country: "JP", timezone: "Asia/Tokyo", utc_offset: "UTC+9" },
    { id: "sydney", city: "悉尼", country: "AU", timezone: "Australia/Sydney", utc_offset: "UTC+11" },
  ],
  serverTimeOffsetMs: 0,

  async init() {
    await this.syncWithServer();
    this.renderCards();
    this.tick();
    setInterval(() => this.tick(), 1000);
    // Re-sync system metrics every 15 seconds
    this.refreshSystemTelemetry();
    setInterval(() => this.refreshSystemTelemetry(), 15000);
  },

  async syncWithServer() {
    try {
      const data = await API.getTimezones();
      if (data && Array.isArray(data.clocks)) {
        this.zones = data.clocks;
      }
      if (data && data.server_utc) {
        const srv = new Date(data.server_utc).getTime();
        if (!Number.isNaN(srv)) {
          this.serverTimeOffsetMs = srv - Date.now();
        }
      }
    } catch (err) {
      console.warn("Using local browser Intl clock fallback:", err);
    }
  },

  renderCards() {
    const grid = document.getElementById("clock-grid");
    if (!grid) return;
    grid.innerHTML = this.zones
      .map(
        (z) => `
      <div class="clock-card" id="clock-card-${z.id}">
        <div class="clock-top">
          <div class="clock-city">
            <span id="clock-icon-${z.id}">☀️</span>
            <span>${z.city}</span>
          </div>
          <span class="clock-tz-badge" id="clock-offset-${z.id}">${z.utc_offset || z.timezone}</span>
        </div>
        <div class="clock-time" id="clock-time-${z.id}">--:--:--</div>
        <div class="clock-bottom">
          <span id="clock-date-${z.id}">----/--/--</span>
        </div>
      </div>
    `
      )
      .join("");
  },

  tick() {
    const now = new Date(Date.now() + this.serverTimeOffsetMs);

    this.zones.forEach((z) => {
      try {
        const timeStr = new Intl.DateTimeFormat("zh-CN", {
          timeZone: z.timezone,
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }).format(now);

        const dateStr = new Intl.DateTimeFormat("zh-CN", {
          timeZone: z.timezone,
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          weekday: "short",
        }).format(now);

        const hourNum = parseInt(timeStr.slice(0, 2), 10);
        const isDay = hourNum >= 6 && hourNum < 19;

        const timeEl = document.getElementById(`clock-time-${z.id}`);
        const dateEl = document.getElementById(`clock-date-${z.id}`);
        const iconEl = document.getElementById(`clock-icon-${z.id}`);

        if (timeEl) timeEl.textContent = timeStr;
        if (dateEl) dateEl.textContent = dateStr;
        if (iconEl) iconEl.textContent = isDay ? "☀️" : "🌙";
      } catch (e) {
        // Fallback to server snapshot
      }
    });
  },

  async refreshSystemTelemetry() {
    try {
      const sys = await API.getSystemStatus();
      const platformEl = document.getElementById("sys-platform-text");
      const summaryEl = document.getElementById("telemetry-summary");
      if (platformEl) {
        platformEl.textContent = sys.platform;
      }
      if (summaryEl) {
        const tempPart = sys.temperature_c !== null ? ` · 🌡️ ${sys.temperature_c}°C` : "";
        summaryEl.textContent = `CPU ${sys.cpu_percent}% · RAM ${sys.memory.used_gb}/${sys.memory.total_gb}GB (${sys.memory.percent}%) · 存储 ${sys.storage.percent}%${tempPart}`;
      }
    } catch (e) {
      // Ignore telemetry error cleanly
    }
  },
};
