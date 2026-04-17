# 部署指南

English: [DEPLOY.md](DEPLOY.md) | 中文: [DEPLOY_CN.md](DEPLOY.md)

---

## 目录

- [快速部署](#快速部署)
- [本地开发部署](#本地开发部署)
- [Docker 部署](#docker-部署)
- [生产环境配置](#生产环境配置)
- [OpenTelemetry 配置](#opentelemetry-配置)
- [HITL 人工审批配置](#hitl-人工审批配置)
- [常见问题](#常见问题)

---

## 快速部署

### 方式一：deploy.sh（推荐本地开发）

```bash
git clone https://github.com/liangfuliang541-pixel/clawswarm.git
cd clawswarm

# 安装依赖
./deploy.sh install-deps

# 启动所有服务（本地模式）
./deploy.sh local

# 查看状态
./deploy.sh status

# 停止所有服务
./deploy.sh stop
```

### 方式二：Hub-Spoke 跨公网部署

```bash
# 主控端：启动 Hub（嵌入 master_api.py）
python master_api.py --port 50010 --hub-port 18080

# 远程 Agent（原生模式）
python networking.py agent --hub-url http://<hub-ip>:18080 --agent-id remote-01

# 远程 Agent（Hermes 适配器）
python networking.py agent --hub-url http://<hub-ip>:18080 --agent-id hermes-01 \
  --adapter-type hermes \
  --adapter-config '{"hermes_bin":"hermes","model":"qwen2.5:72b"}'

# 下发任务
python networking.py client --hub-url http://localhost:18080 \
  --task "Fetch https://httpbin.org/json" --task-type fetch

# 等待结果
python networking.py client --hub-url http://localhost:18080 \
  --wait <task_id>
```

**注意**：如果 Hub 在内网，远程 Agent 需要能访问 Hub 的 18080 端口。
方案：(1) 云安全组开端口，(2) ngrok/cpolar 内网穿透，(3) Cloudflare Tunnel。

### 方式三：Dashboard（Web UI 监控）

```bash
# 启动 Dashboard（自动连接 MonitorService）
python dashboard/dashboard.py --port 5000

# 浏览器打开
# http://localhost:5000
```

Dashboard 功能：节点状态、任务 DAG 可视化、实时事件流、自然语言任务提交。

### 方式四：MCP Server（Agent 间调用）

```bash
# 直接启动 MCP 服务器（stdio 模式）
python mcp_server.py

# 或注册到 mcporter 后使用
mcporter call clawswarm.clawswarm_status
mcporter call clawswarm.clawswarm_submit prompt="task description" priority=8
```

注册配置（一次性）：
```json
// ~/.mcporter/mcporter.json
{
  "mcpServers": {
    "clawswarm": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/path/to/clawswarm"
    }
  }
}
```

### 方式二：Docker Compose（推荐生产部署）

```bash
cp .env.template .env
# 编辑 .env，填入 API key

docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down
```

---

## 本地开发部署

### 前置条件

- Python 3.8+
- pip
- Git

### 步骤

```bash
# 1. 克隆
git clone https://github.com/liangfuliang541-pixel/clawswarm.git
cd clawswarm

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装可选增强包（推荐）
pip install websockets opentelemetry-api opentelemetry-sdk

# 4. 配置环境变量
cp .env.template .env
# 编辑 .env，填入 OPENAI_API_KEY 或 ANTHROPIC_API_KEY

# 5. 启动主服务
python master_api.py &
sleep 2

# 6. 启动事件服务器（可选）
python events.py &

# 7. 启动节点
python node_api.py claw_alpha search write code &
python node_api.py claw_beta analyze report read &

# 8. 验证
curl http://localhost:5000/health
```

**启动后访问**：
- Master API: http://localhost:5000
- Master API 文档: http://localhost:5000/docs
- Event WebSocket: ws://localhost:8765
- Node Alpha: http://localhost:5171
- Node Beta: http://localhost:5172

---

## Docker 部署

### 前置条件

- Docker 20.10+
- Docker Compose v2+

```bash
# 1. 克隆
git clone https://github.com/liangfuliang541-pixel/clawswarm.git
cd clawswarm

# 2. 配置环境变量
cp .env.template .env
# 必须设置：OPENAI_API_KEY 或 ANTHROPIC_API_KEY
# 可选设置：OLLAMA_BASE_URL（本地模型）

# 3. 构建镜像
docker compose build

# 4. 启动所有服务
docker compose up -d

# 5. 查看状态
docker compose ps

# 6. 查看日志
docker compose logs -f master

# 7. 停止
docker compose down
```

### 架构

```
                    ┌──────────────────┐
                    │   Browser/Dashboard │
                    └────────┬─────────┘
                             │ HTTP/WebSocket
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐  ┌──────────────┐  ┌───────────────────┐
│    master     │  │   events     │  │  node-alpha  5171 │
│  :5000 REST   │  │  :8765 WS    │  │  node-beta   5172 │
│  (scheduler)  │◄─┤  (realtime)  │  │  (task exec)     │
└───────┬───────┘  └──────────────┘  └───────────────────┘
        │
        │ File-based queue (shared volume)
        ▼
┌───────────────────────────────────────────┐
│          swarm-data (Docker volume)        │
│  queue/ | in_progress/ | results/         │
└───────────────────────────────────────────┘
```

### 扩展节点

编辑 `docker-compose.yml`，添加更多 node 服务：

```yaml
node-gamma:
  build: .
  ports:
    - "5173:5173"
  environment:
    - CLAWSWARM_BASE_DIR=/data/swarm
  volumes:
    - swarm-data:/data/swarm
  command: ["python", "node_api.py", "claw_gamma", "analyze", "code", "read"]
```

---

## 生产环境配置

### 环境变量

复制 `.env.template` 为 `.env`，配置以下变量：

```bash
# LLM（必须至少配置一个）
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_API_KEY=sk-ant-...

# 默认模型
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-4o-mini

# OpenTelemetry（可选，推荐生产开启）
CLAWSWARM_OTEL_ENABLED=true
CLAWSWARM_OTEL_ENDPOINT=http://jaeger:4317

# HITL 审批
HITL_POLICY_MODE=always_require
HITL_PRIORITY_THRESHOLD=5

# 任务配置
TASK_TIMEOUT_SEC=300
STALE_THRESHOLD_SEC=600
OFFLINE_THRESHOLD_SEC=30
```

### 安全建议

1. **不要提交 .env**：`.env` 已加入 `.gitignore`
2. **使用 Docker Secrets**：生产环境通过 Docker secrets 传递敏感变量
3. **限制 API 访问**：使用反向代理（Nginx）限制外部访问
4. **HTTPS**：生产环境必须使用 HTTPS

### Nginx 反向代理配置

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws {
        proxy_pass http://localhost:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## OpenTelemetry 配置

### 启用追踪

1. 安装依赖：
```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

2. 配置环境变量：
```bash
CLAWSWARM_OTEL_ENABLED=true
CLAWSWARM_OTEL_ENDPOINT=http://localhost:4317
```

3. 启动 Jaeger（可选，用于可视化追踪）：
```bash
docker run -d --name jaeger \
  -e COLLECTOR_OTLP_ENABLED=true \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:1.50
```

4. 访问 Jaeger UI：http://localhost:16686

### Prometheus 指标

```bash
# 启动 Prometheus
docker run -d --name prometheus \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus

# 抓取 Master API metrics
curl http://localhost:5000/metrics
```

**prometheus.yml**：
```yaml
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'clawswarm-master'
    static_configs:
      - targets: ['master:5000']
  - job_name: 'clawswarm-events'
    static_configs:
      - targets: ['events:8765']
```

---

## HITL 人工审批配置

### 启用审批

```bash
# 全部审批
python cli.py set-policy always_require

# 按优先级审批（priority >= 5 才审批）
python cli.py set-policy by_priority --threshold 5

# 测试审批流程
python cli.py test-approval
```

### CLI 审批操作

```bash
# 列出待审批
python cli.py list

# 批准
python cli.py approve <checkpoint_id> --reason "确认无误"

# 拒绝
python cli.py reject <checkpoint_id> --reason "参数不对"

# 查看统计
python cli.py checkpoint-stats
```

### Webhook 审批通知

配置 Webhook URL，自动发送审批通知：

```bash
# .env 配置
CLAWSWARM_HITL_WEBHOOK=https://your-webhook-server.com/approve
```

Webhook 请求格式：
```json
POST /approve
{
  "checkpoint_id": "chk_xxx",
  "task_id": "t_yyy",
  "description": "确认执行高风险任务",
  "created_at": "2026-04-15T12:00:00Z"
}
```

批准响应：
```json
{"action": "approve", "reason": "OK"}
```

拒绝响应：
```json
{"action": "reject", "reason": "不符合要求"}
```

---

## 常见问题

### Q: 节点收不到任务？

1. 检查 master 是否运行：`curl http://localhost:5000/health`
2. 检查节点是否注册：`curl http://localhost:5171/health`
3. 检查 queue 目录是否有文件：`ls queue/`
4. 检查节点日志是否有错误

### Q: WebSocket 连接失败？

```bash
# 检查 websockets 包
pip show websockets

# 如果未安装
pip install websockets>=11.0
```

### Q: OpenTelemetry 追踪不到？

1. 检查 OTEL 端点是否可达
2. 检查 `CLAWSWARM_OTEL_ENABLED=true`
3. 检查 Jaeger 是否运行

### Q: Docker 部署内存不足？

```bash
# 限制容器内存
docker compose up -d --scale master=1 --scale node-alpha=1

# 或编辑 docker-compose.yml 添加：
# deploy:
#   resources:
#     limits:
#       memory: 512M
```

### Q: 任务卡住不动？

```bash
# 检查 stale 任务
python cli.py status

# 手动清理 in_progress（超时任务）
python cli.py clean --stale-only

# 强制重新分配
# 移动 in_progress/t_xxx.json → queue/t_xxx.json
```

### Q: 如何查看实时日志？

```bash
# 本地模式
tail -f logs/*.jsonl

# Docker 模式
docker compose logs -f master
docker compose logs -f node-alpha

# 所有服务
docker compose logs -f
```
