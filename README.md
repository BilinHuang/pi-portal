# Pi 5 Stealth Portal

专为树莓派 5（Raspberry Pi 5）与本地节点打造的轻量级、高隐蔽性个人服务门户与创作工作站。

采用 **Python FastAPI + SQLite (WAL 模式) + 原生 ES6/CSS** 单进程架构，常驻内存低、零碎文件写入，天然适配树莓派 TF 卡长期运行。

---

## 核心特性概览

### 1. 隐形安全模型（Stealth RBAC / 404 伪装）
- **未授权完全隐形**：未解锁的分区（`6+`、`9+`、`12+`、`15+`、`18+`）与服务在前端 DOM 与 API 响应中彻底剔除，不留任何占位符。
- **全局 404 伪装**：越权访问任何受保护 API 或子应用路由时，统一返回与不存在路径完全一致的 `404 Not Found`，防止扫描探测。
- **服务四态实时管控**：管理员可在首页或后台一键切换任意服务的运行状态：
  - `active`（运行中）：正常开放跳转。
  - `disabled`（已关闭）、`offline`（暂不可用）、`wip`（待开发）：卡片自动置灰并拦截跳转。

### 2. 右上角统一身份胶囊与认证体系
- **单胶囊收拢交互**：右上角常驻身份胶囊（`👤 访客 ▾` / `🎟️ 已授权访客 ▾` / `👑 admin ▾`），点击展开下拉菜单（输入激活码、管理中心、登录、注册、退出登录）。
- **双下拉问答验证注册**：
  - **问题一（身份归属题）**：初中（`七宝二中` $\to$ 标记 `初中`）、高中（`交附嘉分/交嘉/绞架` $\to$ 标记 `高中`）、大学（`合工大/肥工/hfut/新南威尔士大学/unsw` $\to$ 标记 `大学`）、小名（`菜菜` $\to$ 标记 `家人`），选择问题后动态展开输入框，验证通过后自动授予对应圈层初始权限。
  - **问题二（生活细节题）**：常玩游戏（`都市天际线 / 原神 / 明日方舟(粥) / 狂热运输2`）或常做运动（`羽毛球`）。
- **1 小时临时注册码**：注册弹窗底部提供灰色小字入口「使用临时验证码注册」，管理员可在后台一键生成 1 小时有效的免问答注册码。

### 3. 管理中心（Admin Panel）与 AI 配额架构
- **账户与密码管理**：支持管理员查看用户所属分类标签（初中/高中/大学/家人）、切换显示明文密码（`👁️`）以及一键重置密码。
- **AI 算力配额与频次限制**：内置按用户维度的每日调用上限（`ai_daily_limit`，`-1` 为无限）与每分钟请求频次（`ai_rpm_limit`），UTC 跨日自动清零重置。

### 4. 内置核心子应用

#### ✍️ 小说创作工坊 (`/apps/story-studio`)
- **多密钥池自动轮询与故障切换 (`keys/*.key`)**：
  - 自动扫描项目根目录下 `keys/` 文件夹中的所有 `.key` 文件（如 `Gemini1.key`、`gemini2.key`）。
  - 支持在 UI 中选择「自动轮询与故障切换」或指定单个 Key；当某个 Key 触发 `429` 限流或配额耗尽时，自动无缝切换至下一个 Key 继续生成。
- **三大创作模式 + 自动加载/可编辑 System Prompt**：
  1. **错乱重写扩写**：阶段 1 解构剧情、主控方/承制方、器物介质、动作行迹与心理压迫点（JSON 分幕）$\to$ 阶段 2 逐幕深度扩写并流式拼接。
  2. **剧情承接续写**：长文自动提炼全局前情概括 + 截取末尾 2000 字即时物理场景，结合走向提示自然推演下一幕。
  3. **灵感起草全篇**：根据核心脑洞规划 3~5 幕递进大纲 $\to$ 逐幕累计前情并展开正文。
  - 切换模式时自动加载对应模式的默认 `System Prompt`（冷峻客观第三人称、器物触感与受力具象化、生理应激反馈、拒绝道德说教），支持在页面直接修改或一键恢复默认。
- **默认 High 深度推理与流式监控**：
  - 默认开启 `High` 推理深度（`thinkingConfig`）与全类别 `BLOCK_NONE`，自动过滤内部思考链，仅将正文通过 SSE 实时流式输出到屏幕，支持随时点击「立即停止」、一键复制全文及历史生成记录回看（自动归档于 `data/studio_outputs/`）。

#### 📖 本地小说阅读 (`/apps/novel-reader`)
- **三层目录结构导航**：
  - **第一层（卷 / Epoch）**：读取 `novels/` 根目录下的卷文件夹（如 `epoch1` ~ `epoch6`）。
  - **第二层（篇章与设定）**：自动区分卷内的**故事篇章文件夹**（如 `双生共振实验`）、**设定/大纲文件夹**（如 `guideline`、`ideas`）以及**卷级文档**（如 `catalog.md`、`naming_convention.md`）。
  - **第三层（章节正文）**：按自然序号排列章节文件（如 `001_对向X轴的齿轮死锁.txt`、`002_第一记反冲的互害破冰.txt`）。
- **沉浸式阅读体验**：支持字号缩放（`A- / A+`）、三套主题（默认暗色 / 暖灰护眼 / 纯黑 OLED）、键盘左右方向键切章，以及基于 `localStorage` 的上次阅读进度记忆与一键续读。

#### 🚀 连接测速 (`/apps/speedtest-node`)
- 纯内存流式测量本机与服务器之间的 **NTP 级时钟偏差（Clock Offset）**、**往返延迟（Ping RTT）**、**网络抖动（Jitter 12 次采样波形）** 与 **上下行带宽（Download / Upload Mbps）**，全程不落盘，零 TF 卡写入损耗。

#### 📋 公告与便签 (`/apps/pi-status-note`)
- 支持公告、备忘、待办与常用运维命令的增删改查、置顶高亮、分类筛选、关键词即时检索与一键复制。

---

## 项目目录结构

```text
portal/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口、路由注册与全局 404 伪装
│   │   ├── config.py            # 全局路径、密钥目录、小说目录与注册题库配置
│   │   ├── database.py          # SQLite WAL 引擎与零损自动 Schema 迁移
│   │   ├── models.py            # ORM 模型 (User, RegistrationInvite, ActivationCode, Service, Note)
│   │   ├── schemas.py           # Pydantic 数据契约
│   │   ├── security.py          # 密码哈希与签名 Cookie 编解码
│   │   ├── dependencies.py      # 身份解析与隐形权限校验
│   │   └── routers/
│   │       ├── auth.py          # 登录、问答验证注册、临时码注册、激活码兑换
│   │       ├── admin.py         # 用户/密码查看改密、1h临时码生成、AI配额、服务管理
│   │       ├── studio.py        # 小说创作工坊 API、多 Key 轮询与 Gemini SSE 流式引擎
│   │       ├── reader.py        # 本地三层小说阅读器目录树与章节读取 API
│   │       ├── ai.py            # 用户级 AI 每日配额与频次管控接口
│   │       ├── speedtest.py     # 纯内存时钟偏差与上下行带宽测速接口
│   │       ├── notes.py         # 节点公告与便签 CRUD 接口
│   │       ├── services.py      # 服务矩阵过滤与内置子应用挂载路由
│   │       └── widgets.py       # 多时区时钟与系统遥测状态接口
│   ├── requirements.txt         # Python 依赖清单
│   └── seed_data.py             # 初始化默认账户、服务卡片、激活码与示例便签
├── frontend/
│   ├── index.html               # 门户主界面（统一身份胶囊、时钟挂件、管理弹窗）
│   ├── css/style.css            # 暗色玻璃拟态样式表
│   └── js/                      # 前端交互脚本 (api.js, clock.js, dashboard.js, auth.js)
├── keys/                        # Gemini API 密钥池目录 (keys/*.key 已被 Git 忽略)
│   ├── README.md                # 密钥存放说明
│   ├── Gemini1.key              # 主 API Key 文件
│   └── gemini2.key              # 备用 API Key 文件
├── novels/                      # 本地三层小说库根目录 (可通过 PORTAL_NOVELS_DIR 自定义)
│   └── epoch6/
│       ├── catalog.md
│       ├── naming_convention.md
│       ├── guideline/
│       ├── ideas/
│       └── 双生共振实验/
│           ├── 001_对向X轴的齿轮死锁.txt
│           └── 002_第一记反冲的互害破冰.txt
├── data/                        # SQLite 数据库与创作工坊生成存档 (Git 忽略)
└── scripts/
    ├── run_dev.sh               # macOS 本地开发一键启动脚本 (python3 -m pip)
    └── deploy_pi.sh             # 树莓派 5 Systemd 生产环境部署脚本
```

---

## 快速上手与配置说明

### 1. 启动本地开发环境 (macOS)
```bash
cd /Users/bilinhuang/Documents/WebApp/Pi/portal
./scripts/run_dev.sh
```
脚本会自动创建 `.venv`、使用 `python3 -m pip` 安装依赖、执行 `seed_data.py` 同步数据库及表结构迁移，并在 `http://127.0.0.1:8000` 启动热重载服务。

### 2. 配置 Gemini 多密钥池 (`keys/`)
在 `keys/` 目录下编辑或新建任意 `.key` 文件（如 `Gemini1.key`、`gemini2.key`），直接填入你的 Gemini API Key 字符串：
```text
AIzaSyYourActualGeminiApiKeyStringHere
```
- 支持放入多个 `.key` 文件，创作工坊会自动加载并支持轮询与 `429` 故障切换。
- `keys/*.key` 已配置在 `.gitignore` 中，不会上传至 Git 仓库。

### 3. 挂载本地三层小说目录 (`novels/`)
- **方式 A**：直接将你的 `epoch1` ~ `epoch6` 文件夹复制或软链接到项目下的 `novels/` 目录中：
  ```bash
  ln -s /path/to/G_S/epoch* /Users/bilinhuang/Documents/WebApp/Pi/portal/novels/
  ```
- **方式 B**：启动时通过环境变量 `PORTAL_NOVELS_DIR` 直接指向你的小说总目录：
  ```bash
  PORTAL_NOVELS_DIR="/path/to/G_S" ./scripts/run_dev.sh
  ```

---

## 预置账号与激活码

- **管理员账号**：`admin` / `admin123`（拥有全部权限与管理中心入口）
- **测试普通账号**：`guest_user` / `user123`
- **预置激活码**：
  - `PASS-18-UNLIMITED`：无限次解锁全部分区
  - `ONLY-18-INFINITE`：无限次解锁私密专区
  - `PASS-15-LIMIT3`：限用 3 次，解锁核心网络及以下分区
  - `PASS-12-ONETIME`：单次有效，解锁云端开发及以下分区
