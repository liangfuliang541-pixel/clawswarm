# API 参考文档

ClawSwarm 提供两种 API 方式：
1. **命令行 API** - 快速使用
2. **Python API** - 编程调用

---

## 命令行 API

### swarm_scheduler.py

主调度器命令行工具。

#### 添加任务

```bash
python swarm_scheduler.py add <任务描述> [选项]
```

**选项：**
| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--type <类型>` | 任务类型 | `general` |
| `--priority <优先级>` | 任务优先级 | 1 |

**示例：**
```bash
# 添加通用任务
python swarm_scheduler.py add "这是一个测试任务"

# 添加调研任务
python swarm_scheduler.py add "调研AI最新进展" --type research

# 添加高优先级任务
python swarm_scheduler.py add "紧急任务" --priority 10
```

#### 查看状态

```bash
python swarm_scheduler.py status
```

输出：
```
  Nodes Online : 3
    - claw_alpha [idle] HB=2s caps=['search', 'write', 'code']
    - claw_beta [idle] HB=1s caps=['read', 'write']
    - claw_gamma [idle] HB=2s caps=['search', 'analyze', 'report']
  Tasks:
    Pending  : 1
    Running  : 0
    Done     : 7
    Failed   : 0
```

#### 查看结果

```bash
# 查看所有结果
python swarm_scheduler.py results

# 查看特定任务结果
python swarm_scheduler.py results <task_id>
```

#### 任务回收

```bash
# 扫描并回收超时任务
python swarm_scheduler.py cleanup
```

#### 实时监控

```bash
# 持续监控（每10秒刷新）
python swarm_scheduler.py watch
```

---

### swarm_node.py

节点客户端命令行工具。

#### 启动节点

```bash
python swarm_node.py <节点ID> [能力1] [能力2] ...
```

**示例：**
```bash
# 启动一个搜索+写作节点
python swarm_node.py my_node search write

# 启动一个代码执行节点
python swarm_node.py code_node code

# 启动一个全栈节点
python swarm_node.py full_node search write code analyze report
```

**环境变量：**
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SWARM_MAX_RUNTIME` | 最大运行时间（秒） | 无限制 |
| `SWARM_POLL_INTERVAL` | 轮询间隔（秒） | 5 |

**示例：**
```bash
# 运行最多10分钟
$env:SWARM_MAX_RUNTIME="600"
python swarm_node.py my_node search write

# 每3秒轮询一次
$env:SWARM_POLL_INTERVAL="3"
python swarm_node.py my_node search
```

---

## Python API

### 基本使用

```python
from swarm_scheduler import create_task, get_task_result, get_online_nodes
from swarm_node import run_node

# 创建任务
task_id, task = create_task(
    prompt="调研AI最新进展",
    task_type="research",
    priority=1
)
print(f"Created task: {task_id}")

# 查看节点
nodes = get_online_nodes()
for node in nodes:
    print(f"Node: {node['node_id']}, Caps: {node['capabilities']}")

# 获取结果
result = get_task_result(task_id)
print(result)
```

### 高级使用

#### 创建任务（完整参数）

```python
task_id = create_task(
    prompt="调研任务详情",
    task_type="research",
    priority=5,
    metadata={
        "skill_required": "search",
        "result_format": "markdown"
    },
    max_retries=3,
    timeout_seconds=600,
    depends_on=["t_xxx", "t_yyy"]  # 依赖其他任务
)
```

#### 自定义执行器

```python
from swarm_node import execute_task

def my_executor(task):
    task_type = task.get("type")

    if task_type == "custom":
        # 自定义处理逻辑
        return {"status": "ok", "result": "custom output"}

    # 使用默认处理
    return execute_task(task)

# 在你的节点中使用
result = my_executor({"type": "custom", "id": "test"})
```

---

## 文件存储

### 目录结构

```
D:\claw\swarm\
├── queue/                     # 待执行任务
│   └── t_{uuid}.json
│
├── in_progress/              # 执行中任务
│   └── t_{uuid}.json
│
├── results/                  # 任务结果
│   └── r_{uuid}.json
│
└── agents/                   # 节点心跳
    └── {node_id}.json
```

### 文件格式

#### 任务文件 (queue/, in_progress/)

```json
{
  "id": "t_xxx",
  "type": "research",
  "prompt": "...",
  "status": "pending",
  "assigned_to": null,
  "created_at": "2026-04-15T12:00:00Z",
  "retry_count": 0,
  "max_retries": 3
}
```

#### 结果文件 (results/)

```json
{
  "task_id": "t_xxx",
  "status": "done",
  "result": "...",
  "node": "claw_alpha",
  "completed_at": "2026-04-15T12:05:00Z"
}
```

#### 节点文件 (agents/)

```json
{
  "node_id": "claw_alpha",
  "capabilities": ["search", "write"],
  "status": "idle",
  "last_heartbeat": "2026-04-15T12:00:00Z"
}
```

---

## 错误码

| 错误码 | 说明 |
|--------|------|
| 0 | 成功 |
| 1 | 任务不存在 |
| 2 | 节点不在线 |
| 3 | 任务已失败 |
| 4 | 超时 |
| 5 | 文件锁定冲突 |

---

## 示例脚本

### 批量添加任务

```python
import swarm_scheduler

tasks = [
    ("调研AI最新进展", "research"),
    ("分析市场趋势", "analyze"),
    ("写一篇报告", "write"),
]

for prompt, task_type in tasks:
    task_id = swarm_scheduler.create_task(prompt, task_type)
    print(f"Created: {task_id}")
```

### 等待任务完成

```python
import time
import swarm_scheduler

task_id = swarm_scheduler.create_task("调研任务")
print(f"Waiting for {task_id}...")

while True:
    result = swarm_scheduler.get_task_result(task_id)
    if result and result.get("status") in ("done", "failed"):
        print(f"Task {result['status']}: {result.get('result', result.get('error'))}")
        break
    time.sleep(5)
```

### 监控集群状态

```python
import swarm_scheduler

while True:
    swarm_scheduler.show_status()
    swarm_scheduler.recover_stale_tasks()
    time.sleep(10)
```


---

## MCP Server API

ClawSwarm provides MCP (Model Context Protocol) interface for other agents.

### Startup

```bash
python mcp_server.py
```

### Register with mcporter

```json
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

### Tools

#### clawswarm_spawn

Launch a sub-lobster to execute a task.

```bash
mcporter call clawswarm.clawswarm_spawn prompt="Search AI news" label="news" timeout=120
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| prompt | string | Yes | Task description (natural language) |
| label | string | No | Unique label (for result aggregation) |
| timeout | number | No | Timeout seconds (default 300) |
| priority | number | No | Priority 1-10 (default 5) |

#### clawswarm_poll

Poll for result file.

```bash
mcporter call clawswarm.clawswarm_poll label="news" timeout=120
```

#### clawswarm_submit

Submit task to queue.

```bash
mcporter call clawswarm.clawswarm_submit prompt="task" mode="spawn" priority=8
```

#### clawswarm_status

Get cluster status.

```bash
mcporter call clawswarm.clawswarm_status
```

#### clawswarm_nodes

List all nodes.

```bash
mcporter call clawswarm.clawswarm_nodes
```

#### clawswarm_aggregate

Aggregate multiple result files.

```bash
mcporter call clawswarm.clawswarm_aggregate --args '{"labels":["research","write"]}'
```

---

## Dashboard REST API

Web UI monitoring panel REST API.

### Startup

```bash
python dashboard/dashboard.py --port 5000
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Cluster status (with MonitorService data) |
| `/api/nodes` | GET | Node list |
| `/api/tasks` | GET | Task history (last 50) |
| `/api/tasks` | POST | Submit new task (async execution) |
| `/api/events` | GET | Event log |
| `/ws` | WS | Real-time WebSocket event stream |

#### POST /api/tasks

```bash
curl -X POST http://localhost:5000/api/tasks   -H "Content-Type: application/json"   -d '{"prompt": "Search latest AI news"}'
```

#### WS /ws

WebSocket event stream. Event types: `task_created`, `task_started`, `task_completed`, `node_status_change`, `heartbeat`.
