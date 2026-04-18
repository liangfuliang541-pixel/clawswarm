# ClawSwarm 模块索引

> 贡献者必读。本文档说明每个模块的职责、接口和设计决策。

English: [MODULES.md](MODULES.md) | 中文: [MODULES_CN.md](MODULES_CN.md)

---

## 模块概览

```
cli.py                      # 入口：所有命令的统一 CLI
orchestrator.py             # 任务编排：分解 / DAG / 聚合
swarm_scheduler.py          # 主调度器：轮询队列 + 分配节点
swarm_node.py               # 节点进程：执行任务 + watchdog
executor.py                 # 任务执行引擎：5 种模式
├── roles.py                # Agent 角色定义（researcher/writer/coder）
├── llm.py                  # LLM 抽象层（openai/anthropic/gemini/ollama）
├── memory.py                # 记忆系统（短期 + 长期）
config.py                   # 配置管理（YAML + 环境变量）
models.py                   # 数据模型（Task/Node/Workflow）
paths.py                    # 路径配置（统一 BASE_DIR）
guard.py                    # 安全隔离（路径白名单 + 命令黑名单）
monitor.py                  # 监控指标（MetricsCollector）
checkpoint.py               # HITL 人工审批
observability.py            # OpenTelemetry 可观察性
events.py                   # WebSocket 事件服务器
webhook.py                  # Webhook 发送器
node_api.py                 # 节点 HTTP API（:5171）
master_api.py               # 主节点 HTTP API + Hub 嵌入（:50010 + :18080）
networking.py               # Hub-Spoke 跨公网通信（HubServer + HubAgent + HubClient）
agent_adapter.py            # 异构 Agent 适配器基类 + 注册表
hermes_adapter.py           # Hermes ACP 协议适配器（stdin/stdout JSON-RPC 2.0）
evolver_adapter.py          # Evolver 适配器（sessions_send / 文件轮询）
openclaw_adapter.py         # 原生 OpenClaw 适配器（HTTP Hub 轮询）
task_queue.py               # 高级任务队列（优先级、重试、延迟、死信队列）
auth.py                     # 认证授权（API Key、JWT、RBAC 权限）
metrics.py                  # Prometheus 指标收集（Counter/Gauge/Histogram/Summary）
tenant.py                   # 多租户隔离（命名空间、RBAC、配额）
federated.py                # 联邦学习协调器（FedAvg/FedProx 聚合）
edge.py                     # 边缘计算适配器（HTTP/MQTT/WebSocket/CoAP）
autoscale.py                # 自动扩缩容（负载感知、冷却策略）
mcp_server.py               # MCP Server：8 tools
clawchat.py                 # Agent 间聊天：SQLite + HTTP API + WebSocket（port 5002）
dashboard/
├── dashboard.py            # Web UI 监控面板（FastAPI + WebSocket）
└── __init__.py
skill/
├── SKILL.md                # OpenClaw Skill 定义（MCP + sessions_spawn 双模式编排）
├── scripts/spawn.py        # 写任务到队列
├── scripts/poll.py         # 轮询结果
└── scripts/aggregate.py    # 聚合结果
examples/
├── 01_quickstart.py        # 快速上手示例
├── 02_parallel.py          # 并行任务示例
└── 04_mcp_demo.py          # MCP 协议调用示例
dead_letter.py              # 死信队列 (Phase 2)
health_scorer.py            # 节点健康评分 (Phase 2)
result_pipeline.py          # 结果聚合流水线
spawn_manager.py            # 文件队列 + 后台线程 spawn 管理
inter_agent_protocol.py     # Agent 间通信协议库
```

---

## 核心模块详解

### `orchestrator.py` — 任务编排器 ⭐

**职责**：将用户输入分解为可执行子任务，构建 DAG，执行并聚合结果。

**关键类**：
```python
class TaskOrchestrator:
    def decompose(self, task: Task, llm: bool = False) -> List[Task]
        # 分解任务为子任务。llm=True 时调用 LLM 判断。
        # 否则用规则分解（classify_task + EXACT_MAP）。

    def execute(self, task: Task, nodes: List[Node]) -> ExecutionResult
        # 调度单个任务到最优节点

    def execute_dag(self, dag: List[Task]) -> List[ExecutionResult]
        # 按 DAG 顺序执行，带依赖等待

    def aggregate(self, results: List[ExecutionResult]) -> str
        # 合并所有子任务结果
```

**DAG 依赖**：通过 `task.depends_on` 指定前置任务 ID。

**LLM 模式**：设置 `llm=True` 后，`decompose()` 会调用 LLM 决定子任务结构。
需要配置 `OPENAI_API_KEY` 或 `ANTHROPIC_API_KEY`。

---

### `swarm_scheduler.py` — 主调度器

**职责**：轮询 `queue/` 目录，将就绪任务分配给最优节点，监控 stale 任务。

**关键逻辑**：
```
轮询间隔：5 秒（可配置）
分配策略：CAPABILITY_MAP 能力感知调度
Stale 检测：600 秒无更新 → 重新分配
节点选择：优先选 idle 节点，按能力匹配
```

**关键函数**：
```python
def assign_task(task_id: str, node_id: str) -> bool
    # 分配任务到指定节点，移动 queue → in_progress

def get_all_tasks() -> List[Task]
    # 遍历 queue/ + in_progress/ 获取所有任务

def get_task_result(task_id: str) -> Optional[dict]
    # 从 results/ 读取任务结果
```

---

### `swarm_node.py` — 节点进程

**职责**：长驻进程，从 master 分配任务，执行，回报结果。

**两种模式**：
- **轮询模式**（默认）：每 3 秒轮询 `queue/` 和 `in_progress/`
- **Watchdog 模式**（push）：文件变化立即响应，更快

**关键函数**：
```python
def execute_task(task: Task) -> ExecutionResult
    # 执行单个任务，调用 executor.py

def complete_task(task_id: str, result: ExecutionResult)
    # 写入 results/r_{task_id}.json

def fail_task(task_id: str, error: str)
    # 标记任务失败
```

**Watchdog 配置**：
```python
USE_WATCHDOG = True          # True=push模式，False=轮询
WATCHDOG_INTERVAL = 1.0     # 文件检查间隔（秒）
```

---

### `executor.py` — 任务执行引擎

**职责**：根据 `task.mode` 选择执行策略。

| Mode | 实现 | 说明 |
|------|------|------|
| `fetch` | `_execute_fetch()` | aiohttp HTTP 请求 ✅ |
| `exec` | `_execute_exec()` | subprocess.run ✅ |
| `python` | `_execute_python()` | exec() 沙箱 ✅ |
| `spawn` | `_execute_spawn()` | 调用 sessions_spawn（待实现）|
| `workflow` | `_execute_workflow()` | 子工作流（待实现）|

**安全**：
- `exec` 模式：经 guard.py 校验命令白名单
- `python` 模式：仅允许内置函数和基础库，禁止 os/system/import

**关键函数**：
```python
class TaskExecutor:
    def execute(self, task: Task) -> ExecutionResult
        # 主入口，分发到对应模式

    def _execute_fetch(self, task) -> ExecutionResult
        # aiohttp GET/POST，结果转 JSON

    def _execute_exec(self, task) -> ExecutionResult
        # subprocess.run(cmd, cwd=BASE_DIR)
        # 超时 60s，stdout+stderr 截断 10KB

    def _execute_python(self, task) -> ExecutionResult
        # exec() in isolated namespace
        # 禁止: os, sys.exit, __import__, open
```

---

### `checkpoint.py` — 人工审批（v0.6 新增）

**职责**：关键任务执行前暂停，等待人工批准。

**审批策略**（全局单例 `HITL_POLICY`）：
| 策略 | 行为 |
|------|------|
| `always_approve` | 全部自动通过 |
| `always_require` | 全部需要审批 |
| `by_priority` | priority >= threshold 才审批 |
| `by_task_type` | 特定 task_type 才审批 |

**使用方式**：
```python
from checkpoint import CheckpointManager, HITL_POLICY, CheckpointType

# 设置策略
HITL_POLICY.set_always_require()  # 全部审批
HITL_POLICY.set_require_above_priority(threshold=5)

# 在 orchestrator 中使用
mgr = CheckpointManager()
if mgr.should_halt(task):
    mgr.create(task.id, CheckpointType.APPROVAL, "确认执行?")
    decision = mgr.wait_for_decision(chk_id, timeout=3600)
    if decision.result == ApprovalResult.REJECTED:
        return error_result

# CLI 审批
# python cli.py approve <checkpoint_id> --reason "OK"
# python cli.py reject <checkpoint_id> --reason "不符合要求"
```

**文件位置**：
- `checkpoint/pending/{id}.json` — 待审批
- `checkpoint/approved/{id}.json` — 已批准
- `checkpoint/rejected/{id}.json` — 已拒绝

---

### `observability.py` — 可观察性（v0.6 新增）

**职责**：分布式追踪 + 指标收集 + 结构化日志。

**四大件**：
| 组件 | 类 | 说明 |
|------|----|------|
| Tracer | `get_tracer()` | OpenTelemetry span，OTLP 导出 |
| Metrics | `MetricsCollector` | Counter/Gauge/Histogram，Prometheus 格式 |
| Logger | `StructuredLogger` | JSON 日志，带 trace_id |
| Events | `EventEmitter` | 事件发射器，listener 模式 |

**Prometheus 端点**（需要 FastAPI）：
```
GET /metrics  → Prometheus 抓取格式
```

**@traced 装饰器**：
```python
from observability import traced

@traced("orchestrator.decompose")
def decompose(...):
    ...
```

**OpenTelemetry 配置**：
```bash
CLAWSWARM_OTEL_ENABLED=true
CLAWSWARM_OTEL_ENDPOINT=http://localhost:4317  # OTLP gRPC
```

---

### `events.py` — WebSocket 事件服务器（v0.6 新增）

**职责**：实时推送任务/检查点/节点事件到浏览器或监控面板。

**启动**：
```bash
python events.py --host 0.0.0.0 --port 8765
```

**HTTP 端点**：
```
GET /health   → {"status": "ok"}
GET /stats    → 实时指标
GET /ws       → WebSocket upgrade
```

**WebSocket 消息协议**：
```json
// 客户端订阅
{"action": "subscribe", "filter": "task.*"}
{"action": "subscribe", "filter": "checkpoint.*"}

// 服务端推送
{"type": "task.started", "data": {...}, "timestamp": "..."}
{"type": "task.completed", "data": {...}, "timestamp": "..."}
{"type": "checkpoint.pending", "data": {...}, "timestamp": "..."}
```

---

### `node_api.py` — 节点 HTTP API

**端口**：5171（第一个节点），5172，5173...

**端点**：
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 节点存活 |
| POST | `/poll` | 节点拉取任务 |
| POST | `/complete` | 节点完成任务 |
| POST | `/fail` | 节点任务失败 |
| GET | `/results/{task_id}` | 读取结果 |
| GET | `/read/{path}` | 读取文件 |
| POST | `/write/{path}` | 写入文件 |

---

### `master_api.py` — 主节点 HTTP API

**端口**：5000

**端点**：
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 主节点存活 |
| GET | `/nodes` | 列出所有节点 |
| POST | `/nodes/register` | 节点注册 |
| GET | `/tasks` | 列出任务（支持过滤）|
| POST | `/tasks` | 创建任务 |
| GET | `/tasks/{id}` | 获取任务详情 |
| GET | `/tasks/{id}/result` | 获取任务结果 |
| GET | `/stats` | 集群统计 |

---

## 配置加载优先级

```
环境变量 > swarm_config.json > 默认值
```

```python
# 读取顺序
os.environ.get("CLAWSWARM_BASE_DIR")  # 最高优先级
→ swarm_config.json["base_dir"]
→ 默认值 "D:/claw/swarm"（Windows）/ "/data/swarm"（Linux）
```

---

## 路径规范

所有路径统一通过 `paths.py` 访问：
```python
from paths import BASE_DIR, QUEUE_DIR, RESULTS_DIR, ...

BASE_DIR      # /data/swarm
QUEUE_DIR     # /data/swarm/queue
RESULTS_DIR   # /data/swarm/results
AGENTS_DIR    # /data/swarm/agents
```

**禁止硬编码路径**。新增目录需在 `paths.py` 中注册。

---

## 测试指南

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行单个模块测试
python -m pytest tests/test_v060.py -v

# 带覆盖率
python -m pytest tests/ --cov=. --cov-report=html

# 测试 v0.6 新增模块
python -m pytest tests/test_v060.py -v
```

**新增测试规范**：
- 文件命名：`tests/test_{module}.py`
- 类命名：`Test{Module}`
- 每个公开函数至少一个测试
- Mock 外部依赖（aiohttp / subprocess）

---

## 代码风格

```bash
# 格式化
black .

# 检查
ruff check .

# 类型检查
mypy .
```

**规范**：
- Python 3.8+
- PEP 8
- 所有模块级函数和类必须有 docstring
- 类型注解（可选但推荐）
- 无 print，用 `from observability import log`

---

### `mcp_server.py` — MCP Server ⭐

**职责**：将 ClawSwarm 暴露为 MCP (Model Context Protocol) 工具，供其他 Agent 调用。

**协议**：stdio JSON-RPC（符合 Anthropic MCP 2024-11-05 规范）

**MCP Tools**：

| Tool | 作用 | 关键参数 |
|------|------|---------|
| `clawswarm_spawn` | 启动子龙虾，写入队列 | prompt, label?, timeout?, priority? |
| `clawswarm_poll` | 轮询等待结果文件 | label, timeout? |
| `clawswarm_submit` | 提交任务到队列 | prompt, mode?, priority? |
| `clawswarm_status` | 集群整体状态 | — |
| `clawswarm_nodes` | 节点列表 | — |
| `clawswarm_aggregate` | 聚合多个结果 | labels[] |

**集成方式**：
```bash
# 注册到 mcporter 后直接调用
mcporter call clawswarm.clawswarm_status
mcporter call clawswarm.clawswarm_submit prompt="task" priority=8
```

**设计决策**：
- 选择 stdio 而非 HTTP，因为 MCP stdio 是最通用的传输方式
- 不依赖外部包（纯 Python 标准库 + json）
- 无 API Key 时优雅降级，返回 demo 数据

---

### `clawchat.py` — Agent 间实时聊天 💬

**职责**：ClawSwarm 集群中不同 Agent 之间的持久化消息系统，支持跨公网 WebSocket 桥接。

**技术栈**：SQLite + FastAPI + WebSocket + RelayBridge

**组件**：
- `ChatStore` — SQLite 消息持久化（inbox / conversation / search）
- `RelayBridge` — 跨公网 WebSocket 桥接（代理消息到 relay）
- `ClawChatServer` — HTTP + WebSocket 服务器（port 5002）
- `ClawChatClient` — 轻量客户端封装

**HTTP API**（port 5002）：

| 端点 | 方法 | 作用 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/inbox/{agent_id}` | GET | 收件箱 |
| `/conversation/{a}/{b}` | GET | 双人聊天记录 |
| `/partners/{agent_id}` | GET | 所有对话对象 |
| `/send/{from}/{to}` | POST | 发送消息 |
| `/ws/{agent_id}` | WS | WebSocket 实时推送 |

**用法示例**：
```python
from clawchat import ChatStore, ClawChatClient

# 收件箱
store = ChatStore()
msgs = store.get_inbox("main-agent")
for m in msgs:
    print(f"{m.from_agent}: {m.content}")

# HTTP API 发送
client = ClawChatClient(base_url="http://localhost:5002", agent_id="main-agent")
client.send("kimi-claw-01", "Hello from the main agent!")
```

**Dashboard 集成**：dashboard/index.html 右下角有内置聊天面板，连接 ClawChatServer，实时收发消息。

---

### `dashboard/dashboard.py` — Web UI 监控面板 🖥️

**职责**：提供 Web UI 实时监控集群状态、任务 DAG、执行结果。

**技术栈**：FastAPI + uvicorn + WebSocket，单 HTML 文件内嵌（零前端依赖）

**REST API**：

| 端点 | 方法 | 作用 |
|------|------|------|
| `/api/status` | GET | 集群整体状态 |
| `/api/nodes` | GET | 节点列表 |
| `/api/tasks` | GET/POST | 任务历史 / 提交新任务 |
| `/ws` | WS | 实时事件流 |

**UI 布局**：
```
┌──────────────┬────────────────────────────┬──────────────┐
│ 🐠 节点面板   │  📊 统计 + DAG 可视化      │ 📋 任务列表   │
│              │  ➕ 任务提交表单             │ 📡 事件日志   │
└──────────────┴────────────────────────────┴──────────────┘
```

**设计决策**：
- 集成 MonitorService：连接时显示 LIVE 模式，否则 DEMO 模式
- DAG 用 CSS absolute 定位，无需额外图表库
- WebSocket 3 秒断线重连 + 右下角连接指示灯

---

## 提交规范

```bash
# 使用 conventional commits
git commit -m 'feat: add HITL checkpoint approval'
git commit -m 'fix: correct path in complete_task'
git commit -m 'docs: update API reference'
git commit -m 'test: add checkpoint tests'
git commit -m 'refactor: extract LLM abstraction'
```


---

### `dead_letter.py` — Dead Letter Queue (Phase 2)

**职责**：管理失败/超时/重试耗尽的任务。

**入口**：失败任务自动进入 DLQ，或手动 enqueue。

| 函数 | 作用 |
|------|------|
| `enqueue(task, reason, detail)` | 写入 DLQ |
| `list_entries(reason, limit)` | 列表查询 |
| `retry(entry_id)` | 重试（移回 queue） |
| `purge(entry_id, reason)` | 清理 |
| `stats()` | 统计 |

**DLQ 原因**：`MAX_RETRIES` / `TIMEOUT` / `NODE_FAILURE` / `MANUAL`

---

### `health_scorer.py` — Node Health Scorer (Phase 2)

**职责**：计算节点健康评分（0-100），5 维加权。

| 维度 | 权重 | 说明 |
|------|------|------|
| heartbeat | 30% | 心跳新鲜度 |
| success_rate | 25% | 任务成功率 |
| load | 20% | CPU + 内存 |
| response_time | 15% | 平均响应时间 |
| error_rate | 10% | 近期错误率 |

**健康级别**：
- 80-100 `healthy`：接受所有任务
- 60-79 `degraded`：仅接受低优先级
- 40-59 `warning`：不接受新任务
- 0-39 `critical`：触发熔断

---

### `result_pipeline.py` — Result Aggregation Pipeline

**职责**：5 阶段结果聚合流水线。

```
Collect → Filter → Transform → Aggregate → Export
```

| 阶段 | 作用 |
|------|------|
| Collect | 扫描 results/ 匹配标签 |
| Filter | 移除 failed/timeout |
| Transform | 提取 output 字段 |
| Aggregate | 合并为统一输出 |
| Export | 写入 pipelines/ 目录 |

**快速使用**：
```python
from result_pipeline import quick_aggregate
result = quick_aggregate(["research", "write"], timeout=60)
```

---

### `networking.py` — 跨公网 Hub-Spoke 通信模块

**架构**：Hub-Spoke 反向轮询模型。Hub 被动接收连接，Agent 主动轮询。

```
Hub (port 18080) ←──── HTTP 轮询 ──── Agent (VM/远程)
```

| 组件 | 角色 | 运行位置 |
|------|------|----------|
| `HubServer` | Hub 端，任务队列 + agent 注册 | 主控机器 |
| `HubAgent` | Agent 端，HTTP client 轮询 Hub | 远程节点 |
| `HubClient` | 主控端 client，主动下发任务 | 主控机器 |

**Hub HTTP API（JSON）**：

| 端点 | 方法 | 作用 |
|------|------|------|
| `/hub/register` | POST | Agent 注册（agent_id, capabilities） |
| `/hub/agents` | GET | 列出所有注册 Agent |
| `/hub/queue/<id>` | GET | Agent 原子 pop 自己的任务队列 |
| `/hub/submit_task` | POST | 主控端向指定 Agent 下发任务 |
| `/hub/submit/<tid>` | POST | Agent 提交任务结果 |
| `/hub/result/<tid>` | GET | 主控端获取任务结果 |
| `/hub/status` | GET | Hub 运行状态 |

**CLI 用法**：

```bash
# Hub 端
python networking.py hub [--port 18080]

# Agent 端（原生执行）
python networking.py agent --hub-url http://<hub-ip>:18080 --agent-id kimi-claw

# Agent 端（Hermes 适配器）
python networking.py agent --hub-url http://<hub-ip>:18080 --agent-id hermes-01 \
  --adapter-type hermes --adapter-config '{"hermes_bin":"hermes"}'

# 主控端下发任务
python networking.py client --hub-url http://localhost:18080 \
  --task "Fetch https://..." --task-type fetch
```

**HubAgent + Adapter 集成**：HubAgent 接受 `adapter_type` 和 `adapter_config` 参数，`execute_task()` 自动委托给对应适配器。

**关键设计**：
- Hub 不需要公网 IP（Agent 主动连 Hub）
- Agent 不需要 inbound 端口（只有 outbound HTTP 请求）
- 任务队列基于文件系统，原子 pop，无 Redis 依赖
- 轮询间隔可配置（默认 3s）

---

### `agent_adapter.py` — 异构 Agent 适配器基类 🔌

**职责**：定义 Agent 适配器抽象接口 + 注册表，让 ClawSwarm 能接入不同类型的 Agent。

**抽象接口**：
```python
class AgentAdapter(ABC):
    ADAPTER_TYPE: str                          # 适配器类型标识
    def start(self) -> bool                    # 启动适配器
    def stop(self) -> None                     # 停止适配器
    async def execute(self, task: dict) -> dict # 执行任务
    def health_check(self) -> dict             # 健康检查
```

**注册表**：
```python
@register_adapter("hermes")
class HermesAdapter(AgentAdapter): ...

adapter = get_adapter("hermes", "hermes-01", {"hermes_bin": "hermes"})
```

**已注册适配器**：

| ADAPTER_TYPE | 类 | 协议 |
|-------------|-----|------|
| `openclaw` | OpenClawAdapter | HTTP Hub 轮询 |
| `hermes` | HermesAdapter | ACP stdin/stdout JSON-RPC 2.0 |
| `evolver` | EvolverAdapter | sessions_send / 文件轮询 |

---

### `hermes_adapter.py` — Hermes ACP 协议适配器

**职责**：通过 ACP (Agent Communication Protocol) 与 Hermes Agent 通信。

**协议流程**：
```
hermes acp → //ready → initialize → authenticate → session/new → session/prompt → 结果
```

**ACP 协议**：stdin/stdout JSON-RPC 2.0，支持流式响应和会话复用。

**配置参数**：
- `hermes_bin`：Hermes 二进制路径（默认 "hermes"）
- `model`：使用的模型（如 "qwen2.5:72b"）
- `capabilities`：能力列表

---

### `evolver_adapter.py` — Evolver 适配器

**职责**：通过 OpenClaw Skill 调用链与 Evolver Agent 通信。

**通信方式**：
1. 优先：`sessions_send` 注入任务到 Evolver session
2. 回退：文件轮询 `.clawswarm_evolver_tasks/` 目录

**配置参数**：
- `workspace`：OpenClaw workspace 路径
- `node_id`：Evolver 节点 ID
- `poll_interval`：轮询间隔（默认 1 秒）

---

### `openclaw_adapter.py` — 原生 OpenClaw 适配器

**职责**：封装 Hub HTTP 注册 + 轮询，让原生 OpenClaw Agent 作为 HubAgent 节点。

**通信方式**：HTTP POST 注册 → GET 轮询任务 → POST 提交结果

---

### `task_queue.py` — 高级任务队列 ⚙

**职责**：提供优先级排序、指数退避重试、延迟执行、死信队列的任务调度。

```python
from task_queue import TaskQueue, TaskPriority

q = TaskQueue()
task = q.submit('task-1', {'cmd': 'echo hello'}, priority=TaskPriority.HIGH, max_retries=3)
next_task = q.get_next('worker-1')  # 获取最高优先级任务
q.complete(next_task.task_id, result='done')
q.fail('task-1', 'timeout')          # 自动进入重试，3次后进死信队列
q.retry_dead()                      # 重试所有死信任务
```

**关键特性**：`heapq` 优先级堆、磁盘持久化、事件回调、延迟调度、配额管理。

---

### `auth.py` — 认证与授权 🔐

**职责**：API Key（SHA256 哈希）+ JWT（HS256 签名）认证，RBAC 四角色权限控制。

```python
from auth import AuthManager, Permission
auth = AuthManager()
key_id, plaintext = auth.create_api_key('my-key', role='operator')
valid = auth.validate_api_key(plaintext)  # 验证 Key
token = auth.create_jwt('user-1', role='admin')   # 生成 JWT
claims = auth.validate_jwt(token)                # 验证 JWT
```

**4 角色**：`admin`（全部权限）、`operator`（读写+执行）、`viewer`（只读）、`agent`（执行）。

---

### `metrics.py` — Prometheus 指标 📊

**职责**：Prometheus 兼容的指标收集，支持 Counter/Gauge/Histogram/Summary 四种类型。

```python
from metrics import get_metrics_registry, init_default_metrics
init_default_metrics()
r = get_metrics_registry()
r.counter('tasks_total').inc()
r.gauge('active_nodes').set(5)
print(r.to_prometheus())  # 导出 Prometheus 文本格式
```

---

### `tenant.py` — 多租户隔离 🏢

**职责**：命名空间隔离、成员管理、配额限制、权限检查。

```python
from tenant import TenantManager
tm = TenantManager()
tenant = tm.create_tenant('team-a', 'Team Alpha', 'user1', quotas={'max_nodes': 20})
tm.add_member(tenant.tenant_id, 'user2', role='member')
tm.check_permission('user2', tenant.tenant_id, 'task:create')  # True
```

---

### `federated.py` — 联邦学习协调器 🧠

**职责**：多节点协作训练，不共享原始数据，支持 FedAvg 和 FedProx 聚合。

```python
from federated import FederatedCoordinator
fc = FederatedCoordinator()
model = fc.register_model('mnist-cnn', 'MNIST', aggregation='fed_avg')
round = fc.start_round(model.model_id, ['node-1', 'node-2'])
fc.submit_update(model.model_id, 'node-1', round.round_id, weights, num_samples=100)
result = fc.complete_round(model.model_id, round.round_id)
```

---

### `edge.py` — 边缘计算适配器 🌐

**职责**：将 IoT 设备接入集群作为轻量 Agent，支持 HTTP/MQTT/WebSocket/CoAP 协议。

```python
from edge import EdgeAdapter
ea = EdgeAdapter()
device = ea.register_device('sensor-01', 'Temp Sensor', 'http', 'http://192.168.1.100:8080',
                            capabilities=['temperature', 'humidity'])
ea.start_heartbeat_monitor()  # 启动心跳监控
```

---

### `autoscale.py` — 自动扩缩容 ⚡

**职责**：基于队列深度和资源使用率自动调整 Agent 池大小。

```python
from autoscale import AutoScaler, ScalePolicy
policy = ScalePolicy(min_nodes=1, max_nodes=10, scale_up_threshold=0.7)
scaler = AutoScaler('pool-1', policy=policy)
scaler.update_pool_state(current_size=3, pending=15, cpu=70.0)
scaler.evaluate()  # 判断是否需要扩缩容
scaler.apply_scaling()  # 执行扩缩容
```

