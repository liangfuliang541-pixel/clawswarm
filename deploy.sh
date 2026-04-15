#!/bin/bash
# ClawSwarm 部署脚本
# ========================
# 用法:
#   chmod +x deploy.sh
#   ./deploy.sh           # 开发模式（本地）
#   ./deploy.sh docker    # Docker 模式
#   ./deploy.sh status    # 查看状态

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
error() { echo -e "${RED}[error]${NC} $1"; exit 1; }

check_python() {
    if ! command -v python3 &> /dev/null; then
        error "Python 3 is required"
    fi
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    log "Python version: $PYTHON_VERSION"
}

check_dependencies() {
    log "Checking dependencies..."
    MISSING=()
    for pkg in aiohttp watchdog requests; do
        if ! python3 -c "import $pkg" 2>/dev/null; then
            MISSING+=($pkg)
        fi
    done
    if [ ${#MISSING[@]} -gt 0 ]; then
        warn "Missing packages: ${MISSING[*]}"
        log "Installing dependencies..."
        pip3 install aiohttp watchdog requests
    fi
}

check_optional() {
    OPTIONAL=("websockets" "opentelemetry-api" "opentelemetry-sdk" "opentelemetry-exporter-otlp" "fastapi" "uvicorn")
    MISSING_OPTIONAL=()
    for pkg in "${OPTIONAL[@]}"; do
        if ! python3 -c "import ${pkg//-/_}" 2>/dev/null; then
            MISSING_OPTIONAL+=($pkg)
        fi
    done
    if [ ${#MISSING_OPTIONAL[@]} -gt 0 ]; then
        warn "Optional packages not installed: ${MISSING_OPTIONAL[*]}"
        warn "Install with: pip3 install ${MISSING_OPTIONAL[*]}"
        warn "These enable: WebSocket events / OpenTelemetry / FastAPI"
    fi
}

check_env() {
    if [ ! -f .env ]; then
        warn ".env file not found. Copying from .env.template..."
        cp .env.template .env
        warn "Please edit .env and set your API keys before starting."
    fi
}

start_local() {
    log "Starting ClawSwarm (local mode)..."

    # 加载 .env
    if [ -f .env ]; then
        set -a
        source .env
        set +a
    fi

    # 创建目录
    mkdir -p queue in_progress results agents memory logs checkpoint

    # 启动主 API（后台）
    log "Starting Master API on :5000..."
    python3 master_api.py &
    MASTER_PID=$!
    sleep 2

    # 启动事件服务器（后台）
    if python3 -c "import websockets" 2>/dev/null; then
        log "Starting Event Server on :8765..."
        python3 events.py &
        EVENTS_PID=$!
    else
        warn "WebSocket not available, skipping event server"
    fi

    # 启动节点（后台）
    log "Starting Node Alpha..."
    python3 node_api.py claw_alpha search write code &
    ALPHA_PID=$!

    sleep 1
    log "Starting Node Beta..."
    python3 node_api.py claw_beta analyze report read &
    BETA_PID=$!

    log "All services started."
    log "Master API:  http://localhost:5000"
    log "Master API docs: http://localhost:5000/docs"
    echo ""
    log "PIDs: master=$MASTER_PID events=$EVENTS_PID alpha=$ALPHA_PID beta=$BETA_PID"
    echo ""
    log "Stop all: kill $MASTER_PID $EVENTS_PID $ALPHA_PID $BETA_PID 2>/dev/null"
}

start_docker() {
    log "Starting ClawSwarm (Docker mode)..."
    if ! command -v docker &> /dev/null; then
        error "Docker is required. Install from https://docker.com"
    fi
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        error "Docker Compose is required."
    fi

    check_env

    log "Building Docker images..."
    docker compose build

    log "Starting services..."
    docker compose up -d

    sleep 5

    log "Services:"
    docker compose ps

    echo ""
    log "Master API:  http://localhost:5000"
    log "Event WS:    ws://localhost:8765"
    log "Node Alpha:  http://localhost:5171"
    log "Node Beta:   http://localhost:5172"
    log ""
    log "View logs:   docker compose logs -f"
    log "Stop:        docker compose down"
}

show_status() {
    log "Checking service status..."
    echo ""

    # Master API
    if curl -sf http://localhost:5000/health &>/dev/null; then
        log "Master API:   ${GREEN}UP${NC} (http://localhost:5000)"
    else
        warn "Master API:   ${RED}DOWN${NC}"
    fi

    # Event Server
    if curl -sf http://localhost:8765/health &>/dev/null; then
        log "Event Server: ${GREEN}UP${NC} (ws://localhost:8765)"
    else
        warn "Event Server: ${RED}DOWN${NC}"
    fi

    echo ""

    # Node APIs
    for port in 5171 5172 5173; do
        if curl -sf "http://localhost:$port/health" &>/dev/null; then
            log "Node (:$port): ${GREEN}UP${NC}"
        else
            warn "Node (:$port): ${RED}DOWN${NC}"
        fi
    done

    echo ""

    # Tasks
    TASKS=$(curl -sf http://localhost:5000/tasks 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null || echo "N/A")
    log "Total tasks: $TASKS"
}

# ── 入口 ───────────────────────────────────────────────────────────────────

MODE=${1:-local}

case "$MODE" in
    local)
        check_python
        check_dependencies
        check_optional
        start_local
        ;;
    docker)
        start_docker
        ;;
    status)
        show_status
        ;;
    stop)
        log "Stopping all services..."
        pkill -f "master_api.py" 2>/dev/null || true
        pkill -f "node_api.py" 2>/dev/null || true
        pkill -f "events.py" 2>/dev/null || true
        log "Done."
        ;;
    install-deps)
        check_python
        pip3 install -r requirements.txt
        pip3 install websockets opentelemetry-api opentelemetry-sdk fastapi uvicorn
        log "All dependencies installed."
        ;;
    *)
        echo "ClawSwarm Deploy Script"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  local      Start services locally (default)"
        echo "  docker     Start services with Docker Compose"
        echo "  status     Show service status"
        echo "  stop       Stop all local services"
        echo "  install-deps  Install Python dependencies"
        echo ""
        echo "Examples:"
        echo "  $0 install-deps"
        echo "  $0 local"
        echo "  $0 docker"
        ;;
esac
