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
master_api.py               # 主节点 HTTP API（:5000）
mcp_server.py               # MCP Server：6 tools（spawn/poll/submit/status/nodes/aggregate）
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
