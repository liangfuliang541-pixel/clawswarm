#!/bin/bash
# ClawSwarm Relay Server 启动脚本
# 用法: ./start_relay.sh [--port 18080]
# 依赖: Python 3.8+

PORT=${1:-18080}

echo "======================================"
echo "ClawSwarm Relay Server"
echo "======================================"
echo "端口: $PORT"
echo "数据目录: $(dirname $0)/relay_data"
echo ""

# 检测 Python
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo "❌ 未找到 Python，请先安装"
        exit 1
    fi
    PYTHON=python
else
    PYTHON=python3
fi

# 启动 relay server
echo "🚀 启动 Relay Server..."
$PYTHON "$(dirname $0)/relay_server.py" --port $PORT --host 0.0.0.0
