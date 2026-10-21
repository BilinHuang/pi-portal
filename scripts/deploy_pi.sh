#!/usr/bin/env bash
# 树莓派 5 生产环境部署与 Systemd 服务安装脚本
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="pi-dashboard"
USER_NAME="$(whoami)"
PORT="${PORT:-8000}"

cd "$PROJECT_DIR"

echo "1. 创建虚拟环境并安装依赖..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "2. 初始化 SQLite WAL 数据库与种子数据..."
python backend/seed_data.py

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "3. 生成 systemd 守护进程配置: ${SERVICE_FILE}"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Pi 5 Stealth Dashboard Service
After=network.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${PROJECT_DIR}
Environment="DASHBOARD_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --no-access-log
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "4. 启动并设置开机自启..."
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo "✅ 部署完成！服务运行在端口 ${PORT}（已关闭高频访问日志以保护 TF 卡寿命）。"
echo "查看状态: sudo systemctl status ${SERVICE_NAME}"
