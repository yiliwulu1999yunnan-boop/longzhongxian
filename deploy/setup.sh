#!/usr/bin/env bash
# 笼中仙 AI 招聘助手 — 一键部署脚本
# 用法: bash deploy/setup.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
SERVICE_NAME="longzhongxian"
SERVICE_FILE="$PROJECT_DIR/deploy/${SERVICE_NAME}.service"

echo "=== 笼中仙部署脚本 ==="
echo "项目目录: $PROJECT_DIR"

# ─── 1. 检查 Python 版本 ───
echo ""
echo "[1/7] 检查 Python 版本..."
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$("$cmd" -c "import sys; print(sys.version_info.major)")
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)")
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON_CMD="$cmd"
            echo "  找到 $cmd (版本 $version)"
            break
        fi
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    echo "  错误: 需要 Python 3.11+，请先安装"
    exit 1
fi

# ─── 2. 创建虚拟环境 + 安装依赖 ───
echo ""
echo "[2/7] 创建虚拟环境并安装依赖..."
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    echo "  虚拟环境已创建: $VENV_DIR"
else
    echo "  虚拟环境已存在，跳过创建"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -e "$PROJECT_DIR"
echo "  依赖安装完成"

# ─── 3. 安装 Playwright 浏览器 ───
echo ""
echo "[3/7] 安装 Playwright 浏览器..."
"$VENV_DIR/bin/playwright" install --with-deps chromium
echo "  Playwright Chromium 已安装"

# ─── 4. 环境变量配置 ───
echo ""
echo "[4/7] 检查环境变量配置..."
ENV_FILE="$PROJECT_DIR/.env.local"
if [ ! -f "$ENV_FILE" ]; then
    cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
    echo "  已从 .env.example 复制 .env.local"
    echo "  *** 请编辑 $ENV_FILE 填入实际值后重新运行此脚本 ***"
    exit 0
else
    echo "  .env.local 已存在"
fi

# ─── 5. 验证环境 ───
echo ""
echo "[5/7] 验证环境配置..."
"$VENV_DIR/bin/python" "$PROJECT_DIR/scripts/check_env.py"

# ─── 6. 数据库迁移 ───
echo ""
echo "[6/7] 运行数据库迁移..."
cd "$PROJECT_DIR"
"$VENV_DIR/bin/alembic" upgrade head
echo "  数据库迁移完成"

# ─── 7. 安装 systemd 服务 ───
echo ""
echo "[7/7] 安装 systemd 服务..."
SYSTEMD_LINK="/etc/systemd/system/${SERVICE_NAME}.service"
if [ -L "$SYSTEMD_LINK" ] || [ -f "$SYSTEMD_LINK" ]; then
    echo "  服务文件已存在，更新..."
    sudo rm -f "$SYSTEMD_LINK"
fi
sudo ln -s "$SERVICE_FILE" "$SYSTEMD_LINK"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
echo "  服务已启用并启动"

echo ""
echo "=== 部署完成 ==="
echo "查看状态: sudo systemctl status $SERVICE_NAME"
echo "查看日志: journalctl -u $SERVICE_NAME -f"
