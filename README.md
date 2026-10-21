# Pi Stealth Dashboard

一个专为树莓派 5（Raspberry Pi 5）打造的轻量级、高隐蔽性个人服务仪表盘（Dashboard）。

本项目集成了多时区时钟挂件、跨平台系统负载监控、外链应用跳转，以及基于年龄/分级体系（`6+`、`9+`、`12+`、`15+`、`18+`）的**隐形权限模型（Stealth RBAC）**。

---

## 核心设计理念

1. **TF 卡友好与极低开销**
   - 树莓派 5 搭配 TF 卡运行，需尽量避免碎文件高频随机读写。
   - 采用 **Python FastAPI + SQLite (WAL 模式)** 单进程架构，常驻内存仅约 50~80MB，空闲 CPU 占用几乎为 0。
   - 前端采用现代原生 ES6+ / CSS，由 FastAPI 统一伺服静态资源，无多余 Node.js 常驻守护进程。

2. **隐形安全模型（Stealth Security / 404 伪装）**
   - **完全隐形**：未授权的分类与服务在前端 UI 和 API 返回的 JSON 中彻底剔除，不留占位符或锁定标识。
   - **404 隐蔽伪装**：若外部用户/扫描器试图直接访问未解锁的 API 或服务跳转路由，后端统一返回标准 `404 Not Found`（绝不返回 `401 Unauthorized` 或 `403 Forbidden`），让未授权路由在公网上不可被嗅探。

3. **双轨凭据与激活码机制**
   - **注册用户**：支持账号密码登录，登录后可兑换激活码将权限绑定至个人账号。
   - **访客免密激活**：访客无需注册，输入激活码即可换取专属 Session Cookie，立即解锁对应分类。
   - **次数限制**：激活码支持配置最大使用次数（例如限用 5 次）或无限次（`-1`）。

4. **挂件与应用目录**
   - **挂件区**：默认提供上海（`Asia/Shanghai`）、东京（`Asia/Tokyo`）、悉尼（`Australia/Sydney`）多地实时时间与时差对比。
   - **应用区**：按等级分类（`6+` ~ `18+`）展示应用卡片，点击支持同域代理或新标签页直达独立应用。

---

## 项目目录结构

```text
dashboard/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI 应用入口，配置静态托管与异常捕获
│   │   ├── config.py            # 全局配置、密钥、数据库路径
│   │   ├── database.py          # SQLite 引擎、WAL 模式初始化、SessionLocal
│   │   ├── models.py            # 数据库模型（用户、激活码、服务、授权记录）
│   │   ├── schemas.py           # Pydantic 输入输出契约
│   │   ├── security.py          # 密码加盐哈希、Cookie Session 编解码
│   │   ├── dependencies.py      # 鉴权依赖注入：身份解析、404 隐形校验
│   │   └── routers/
│   │       ├── auth.py          # 登录/登出/访客通行码兑换/当前身份查询
│   │       ├── services.py      # 服务列表（按权过滤）、安全跳转路由
│   │       └── widgets.py       # 多地时钟数据、跨平台系统状态接口
│   ├── requirements.txt         # Python 依赖清单
│   └── seed_data.py             # 预置默认管理员、测试服务和激活码
├── frontend/
│   ├── index.html               # 仪表盘单页骨架
│   ├── css/
│   │   └── style.css            # 暗黑玻璃拟态质感风格、自适应网格布局
│   └── js/
│       ├── api.js               # 请求层封装（Fetch 与错误处理）
│       ├── clock.js             # 多时区时钟实时挂件脚本
│       ├── dashboard.js         # 仪表盘服务分类动态渲染与隐形控制
│       └── auth.js              # 登录与激活码兑换模态框交互
├── data/                        # 数据持久化目录（Git 忽略）
│   └── dashboard.db             # SQLite 数据库文件
├── scripts/
│   ├── run_dev.sh               # macOS 本地热重载启动脚本
│   └── deploy_pi.sh             # 树莓派 systemd 服务部署脚本
└── README.md                    # 本文档
```

---

## 数据库模型设计 (Database Schema)

### 1. `users` (用户表)
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | 自增主键 |
| `username` | VARCHAR(50) UNIQUE | 用户名 |
| `password_hash` | VARCHAR(255) | 加盐哈希密码 |
| `role` | VARCHAR(20) | 角色 (`admin` / `user`) |
| `created_at` | DATETIME | 注册时间 |

### 2. `activation_codes` (激活码表)
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | 自增主键 |
| `code` | VARCHAR(64) UNIQUE | 激活口令（如 `INFINITE-18-PASS`） |
| `grant_tier` | VARCHAR(10) | 授权分类（`6+` / `9+` / `12+` / `15+` / `18+`） |
| `grant_service_slug` | VARCHAR(50) | 授权特定单应用标识（可选） |
| `max_uses` | INTEGER | 最大使用次数（`-1` 为无限次） |
| `used_count` | INTEGER | 当前已消耗次数 |
| `is_active` | BOOLEAN | 是否可用 |
| `created_at` | DATETIME | 创建时间 |

### 3. `services` (挂载应用表)
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | 自增主键 |
| `slug` | VARCHAR(50) UNIQUE | 唯一路由标识（如 `immich`, `vault`） |
| `name` | VARCHAR(100) | 展示名称 |
| `description` | TEXT | 简介 |
| `icon` | VARCHAR(50) | 图标标识符 |
| `tier` | VARCHAR(10) | 默认准入分级（`6+` / `9+` / `12+` / `15+` / `18+`） |
| `target_url` | VARCHAR(255) | 目标跳转 URL |
| `open_in_new_tab` | BOOLEAN | 是否新窗口打开 |
| `sort_order` | INTEGER | 排序权重 |

### 4. `user_permissions` (用户/访客已解锁权限记录)
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | 自增主键 |
| `user_id` | INTEGER (NULLABLE) | 关联用户 ID（访客为 NULL） |
| `session_token` | VARCHAR(64) (NULLABLE) | 访客会话标识（已登录用户为 NULL） |
| `unlocked_tier` | VARCHAR(10) | 已解锁分级 |
| `unlocked_service_slug` | VARCHAR(50) | 已解锁单个应用 |
| `created_at` | DATETIME | 激活时间 |

---

## 核心 API 设计

### 认证与身份 (`/api/auth`)
* `POST /api/auth/login`：账号密码登录，下发 HttpOnly Session Cookie。
* `POST /api/auth/guest-activate`：访客兑换激活码，校验次数后下发包含访客 Token 的 Cookie。
* `POST /api/auth/redeem-code`：已登录用户兑换激活码，将权限写入用户账号。
* `GET /api/auth/me`：获取当前登录身份及拥有的分级权限集合。
* `POST /api/auth/logout`：清除登录与激活 Cookie。

### 服务与路由伪装 (`/api/services`)
* `GET /api/services`：
  - **核心逻辑**：根据调用者身份动态查询已解锁分级与服务。
  - **输出**：仅包含当前身份可见的分级和应用卡片（无权访问的数据源头剔除）。
* `GET /api/services/launch/{slug}`：
  - **核心逻辑**：校验当前身份是否拥有该 `slug` 对应的服务或分级权限。
  - **权限不足**：直接响应 `404 Not Found`。
  - **权限充足**：重定向 (`307/302`) 至目标 `target_url` 或返回校验成功跳转凭据。

### 小部件 (`/api/widgets`)
* `GET /api/widgets/timezones`：返回上海、东京、悉尼的标准时区标识、当前时间与相对于 UTC 的偏移量。
* `GET /api/widgets/system`：跨平台系统负载与内存占用（开发阶段在 macOS 输出本机指标或 Mock 数据，部署在树莓派时读取硬件状态）。

---

## 快速上手与本地开发 (macOS)

### 1. 环境准备
```bash
cd /Users/bilinhuang/Documents/WebApp/Pi/dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 2. 初始化数据库与预置数据
```bash
python backend/seed_data.py
```

### 3. 启动开发服务器
```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```
访问 `http://127.0.0.1:8000` 即可进入 Dashboard。

---

## 预置测试账号与激活码说明

运行 `seed_data.py` 后将生成以下初始测试凭据：

### 1. 管理员与测试账号
* **管理员**：`admin` / `admin123`（默认解锁全部 `6+` ~ `18+` 分级与服务）
* **普通账号**：`guest_user` / `user123`（默认仅具备基础 `6+` 分级）

### 2. 测试激活码
* `PASS-18-UNLIMITED`：**无限次**使用，解锁 `18+` 全部分类与服务。
* `PASS-15-LIMIT3`：**限制 3 次**使用，解锁 `15+` 分类。
* `PASS-12-ONETIME`：**单次可用**（使用 1 次后作废），解锁 `12+` 分类。
* `PASS-APP-SECRET`：**单应用专属**激活码，解锁指定单个私有服务。

---

## 生产环境部署（树莓派 5 + Cloudflare）

1. **Systemd 守护运行**：在树莓派上配置 systemd service，实现开机自启与异常自动重启。
2. **Cloudflare Tunnel 接入**：
   - 树莓派安装 `cloudflared`，打通安全出网隧道，避免在家庭路由器暴露端口。
   - 配合后端的 404 伪装，全站具备防嗅探能力。
