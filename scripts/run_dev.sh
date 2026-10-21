#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
  echo "📦 正在创建 Python 虚拟环境 (.venv)..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "📥 正在检查并安装依赖..."
pip install -q -r backend/requirements.txt

echo "🌱 正在初始化数据库与测试数据..."
python backend/seed_data.py

echo "🚀 启动 Pi Stealth Dashboard (开发模式): http://127.0.0.1:8000"
exec uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
