#!/usr/bin/env bash
# 树莓派生产环境彻底更新与重启脚本 (One-Click Update & Hard Restart)
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="pi-dashboard"

cd "$PROJECT_DIR"
echo "=========================================="
echo "🔄 正在更新并彻底重启 Pi 生产服务..."
echo "=========================================="

echo "1. 拉取 GitHub 最新代码..."
git pull

echo "2. 激活虚拟环境并安装最新依赖..."
if [ -d ".venv" ]; then
  source .venv/bin/activate
  python3 -m pip install -q -r backend/requirements.txt
else
  python3 -m venv .venv
  source .venv/bin/activate
  python3 -m pip install -q -r backend/requirements.txt
fi

echo "3. 同步数据库迁移与种子配置..."
python3 backend/seed_data.py

echo "4. 重启 systemd 后台常驻服务 (${SERVICE_NAME})..."
sudo systemctl daemon-reload
sudo systemctl restart "${SERVICE_NAME}"

echo "=========================================="
echo "✅ 重启完成！正在检查运行状态:"
echo "=========================================="
sudo systemctl status "${SERVICE_NAME}" --no-pager
