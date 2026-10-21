# Gemini API Keys 目录 (`keys/`)

在此目录下存放你的 Gemini API Key 文件。系统会自动扫描所有 `*.key` 文件并支持**多 Key 自动轮询与限流故障切换（Failover）**。

## 命名与存放规范
- 支持任意数量的 `.key` 文件，例如：
  - `Gemini1.key`
  - `gemini2.key`
  - `gemini3.key`
- 每个文件内直接粘贴对应的单个 API Key 字符串（如 `AIzaSy...`），系统会自动忽略空行及以 `#` 开头的注释行。
- 安全机制：`keys/*.key` 已被加入 `.gitignore`，你的真实密钥不会被提交到 Git 仓库。
