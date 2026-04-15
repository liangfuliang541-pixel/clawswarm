# ClawSwarm MCP Server 工具文档

> MCP (Model Context Protocol) — Anthropic 主导的 AI 工具扩展标准
> ClawSwarm MCP Server 将集群核心能力暴露为 MCP tools，供其他 Agent 调用。
> 版本：0.7.0 | MCP 协议版本：2024-11-05

---

## 目录

1. [clawswarm_spawn](#clawswarm_spawn) — 启动子龙虾执行任务
2. [clawswarm_poll](#clawswarm_poll) — 轮询等待结果文件
3. [clawswarm_submit](#clawswarm_submit) — 提交任务到队列
4. [clawswarm_status](#clawswarm_status) — 获取集群整体状态
5. [clawswarm_nodes](#clawswarm_nodes) — 列出所有节点
6. [clawswarm_aggregate](#clawswarm_aggregate) — 聚合多个结果文件
7. [clawswarm_dead_letter](#clawswarm_dead_letter) — 死信队列管理
8. [clawswarm_health](#clawswarm_health) — 节点健康检查
9. [clawswarm_remote_exec](#clawswarm_remote_exec) — 跨公网节点执行命令
10. [clawswarm_remote_register](#clawswarm_remote_register) — 注册远程节点
11. [clawswarm_remote_list](#clawswarm_remote_list) — 列出已注册远程节点

---

## 运行方式

```bash
# 直接运行（stdio 模式）
python mcp_server.py

# 通过 mcporter 调用
mcporter call --stdio -- python mcp_server.py clawswarm_spawn '{"prompt":"Hello"}'
```

---

## clawswarm_spawn

启动一个子龙虾（sub-agent）执行任务，写入队列后返回 task_id 和结果文件路径。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `prompt` | string | ✅ | 任务描述（自然语言） |
| `label` | string | 否 | 唯一标签，用于结果聚合，默认 `mcp_{timestamp}` |
| `timeout` | number | 否 | 超时秒数，默认 300 |
| `priority` | number | 否 | 优先级 1-10，默认 5 |
| `capabilities` | string[] | 否 | 节点能力要求 |

**返回：**

```json
{
  "task_id": "mcp_news_1712345678",
  "status": "spawned",
  "task_file": "swarm_data/queue/task_mcp_news_1712345678.json",
  "result_file": "swarm_data/results/r_mcp_news_1712345678.json",
  "poll_url": "clawswarm_poll(label='news', timeout=300)"
}
```

**示例：**

```json
{
  "prompt": "搜索2026年AI最新进展，输出一份报告",
  "label": "ai-news",
  "priority": 8,
  "timeout": 600
}
```

---

## clawswarm_poll

轮询等待结果文件出现（通过 label 匹配），超时则返回 timeout 状态。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `label` | string | ✅ | 任务标签（与 spawn 时一致） |
| `timeout` | number | 否 | 轮询超时秒数，默认 300 |

**返回：**

```json
{
  "status": "success",
  "output": "报告内容...",
  "result_file": "swarm_data/results/r_mcp_ai-news_1712345678.json",
  "elapsed": 12.3
}
```

状态值：`success` | `failed` | `timeout` | `unknown`

**示例：**

```json
{
  "label": "ai-news",
  "timeout": 600
}
```

---

## clawswarm_submit

直接提交任务到队列（不等待执行），支持指定执行模式。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `prompt` | string | ✅ | 任务描述 |
| `mode` | string | 否 | 执行模式：`spawn`/`fetch`/`exec`/`python`，默认 `spawn` |
| `priority` | number | 否 | 优先级 1-10，默认 5 |

**返回：**

```json
{
  "task_id": "task_1712345678",
  "status": "submitted",
  "task_file": "swarm_data/queue/task_task_1712345678.json",
  "mode": "spawn"
}
```

**示例：**

```json
{
  "prompt": "分析MCP协议并给出实现建议",
  "mode": "exec",
  "priority": 7
}
```

---

## clawswarm_status

获取 ClawSwarm 集群整体状态，包括节点数、队列深度、任务统计等。

**参数：** 无

**返回：**

```json
{
  "nodes": {
    "total": 3,
    "online": 2,
    "list": [...]
  },
  "queue_depth": 5,
  "active_tasks": 2
}
```

如果 MonitorService 不可用，返回基本信息加 note 标注。

---

## clawswarm_nodes

列出所有已知节点及其状态。

**参数：** 无

**返回：**

```json
{
  "total": 3,
  "online": 2,
  "list": [
    {
      "node_id": "node-alpha",
      "status": "online",
      "capabilities": ["search", "write"],
      "completed_tasks": 42
    }
  ]
}
```

---

## clawswarm_aggregate

读取多个 label 对应的结果文件并聚合成一个响应。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `labels` | string[] | ✅ | 结果标签列表 |

**返回：**

```json
{
  "aggregated": {
    "news": {"status": "success", "output": "...", "file": "..."},
    "report": {"status": "success", "output": "...", "file": "..."}
  },
  "total": 2,
  "found": 2
}
```

**示例：**

```json
{
  "labels": ["news", "report", "summary"]
}
```

---

## clawswarm_dead_letter

管理死信队列（Dead Letter Queue），处理失败/超时任务。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | string | 否 | 操作：`list`/`retry`/`purge`/`stats`，默认 `list` |
| `entry_id` | string | 否 | 特定条目 ID（retry/purge 时需要） |
| `reason` | string | 否 | 按原因过滤（list/purge 时使用） |
| `limit` | number | 否 | 最大返回条目数，默认 20 |

**返回示例（action=list）：**

```json
{
  "entries": [
    {
      "id": "dlq_task_abc_1712345678",
      "original_task_id": "task_abc",
      "reason": "max_retries_exceeded",
      "enqueued_at": "2026-04-16T10:00:00",
      "retry_count": 3
    }
  ]
}
```

**返回示例（action=stats）：**

```json
{
  "total": 12,
  "by_reason": {
    "max_retries_exceeded": 8,
    "execution_timeout": 4
  }
}
```

---

## clawswarm_health

节点健康检查，支持两种模式：

1. **远程节点**：若 `node_id` 为已注册的远程节点，通过 Relay 执行健康检查
   - 检测 relay 连通性、gateway 状态、响应时间
   - 结果写入 `health/{node_id}.json`
2. **本地节点**：使用 `health_scorer` 基于指标计算健康评分

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `node_id` | string | 否 | 节点 ID（远程节点时自动走 relay 检查） |
| `cpu` | number | 否 | CPU 使用率 0-100（本地计算时） |
| `memory` | number | 否 | 内存使用率 0-100（本地计算时） |
| `successful_tasks` | number | 否 | 成功任务数（默认 0） |
| `failed_tasks` | number | 否 | 失败任务数（默认 0） |
| `avg_response_ms` | number | 否 | 平均响应时间 ms（本地计算时） |

**返回（远程节点 relay 检查）：**

```json
{
  "total": 1,
  "healthy": 1,
  "unhealthy": 0,
  "nodes": [
    {
      "node_id": "kimi-claw-01",
      "node_name": "Kimi Claw",
      "relay_reachable": true,
      "gateway_status": "ok",
      "response_time_ms": 234.5,
      "last_heartbeat": "2026-04-16 10:30:00",
      "is_healthy": true,
      "capabilities": ["shell", "general"],
      "health_file": "swarm_data/health/kimi-claw-01.json"
    }
  ]
}
```

**返回（本地健康评分）：**

```json
{
  "node_id": "node-alpha",
  "score": 87.5,
  "level": "healthy",
  "breakdown": {
    "heartbeat": 100,
    "success_rate": 95,
    "load": 80,
    "response_time": 85,
    "error_rate": 90
  },
  "recommendation": "Node is healthy, accept all tasks.",
  "should_accept_tasks": true
}
```

健康等级：
- `healthy`（80-100）：接受所有任务
- `degraded`（60-79）：仅接受低优先级任务
- `warning`（40-59）：不接受新任务，监控
- `critical`（0-39）：触发熔断，拒绝所有任务

---

## clawswarm_remote_exec

通过 HTTP Relay 在远程 OpenClaw 节点上执行命令。用于跨公网节点控制（两台机器不在同一局域网时）。

**前提条件：** 节点必须先通过 `clawswarm_remote_register` 注册。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `node_id` | string | 否* | 已注册节点 ID（与 `relay_url` 二选一） |
| `relay_url` | string | 否* | 直接指定 relay URL（与 `node_id` 二选一） |
| `command` | string | ✅ | 要在远程节点执行的 shell 命令 |
| `wait` | boolean | 否 | 是否等待结果，默认 `true` |
| `timeout` | number | 否 | 超时秒数，默认 60 |

*`node_id` 和 `relay_url` 至少提供一个。

**返回：**

```json
{
  "node_id": "kimi-claw-01",
  "relay_url": "https://xxxx.serveo.net",
  "status": "ok",
  "output": "Ubuntu 22.04\n...",
  "elapsed_seconds": 3.45,
  "command": "uname -a"
}
```

**示例：**

```json
{
  "node_id": "kimi-claw-01",
  "command": "openclaw gateway status",
  "timeout": 30
}
```

---

## clawswarm_remote_register

将远程 OpenClaw 节点注册到 ClawSwarm 集群（通过 HTTP Relay）。

注册后节点可被 `clawswarm_remote_exec` 和 `clawswarm_health` 使用。

**前提条件：** 远程节点已启动 serveo.net SSH 隧道并运行 relay 脚本。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `node_id` | string | ✅ | 唯一节点 ID（如 `kimi-claw-01`） |
| `relay_url` | string | ✅ | HTTP Relay 公网地址（如 `https://xxxx.serveo.net`） |
| `name` | string | 否 | 节点显示名，默认等于 `node_id` |
| `capabilities` | string[] | 否 | 节点能力列表，默认 `["shell", "general"]` |

**返回：**

```json
{
  "status": "registered",
  "node_id": "kimi-claw-01",
  "config": "swarm_data/remote_nodes/kimi-claw-01.json",
  "connection_test": "ok"
}
```

**示例：**

```json
{
  "node_id": "kimi-claw-01",
  "relay_url": "https://xxxx.serveo.net",
  "name": "Kimi Ubuntu",
  "capabilities": ["shell", "openclaw", "web"]
}
```

---

## clawswarm_remote_list

列出所有已注册的远程节点及其状态。

**参数：** 无

**返回：**

```json
{
  "total": 2,
  "nodes": [
    {
      "node_id": "kimi-claw-01",
      "name": "Kimi Claw",
      "type": "remote",
      "relay_url": "https://xxxx.serveo.net",
      "capabilities": ["shell", "general"],
      "relay_reachable": true,
      "pending_command": "",
      "config_file": "swarm_data/remote_nodes/kimi-claw-01.json"
    }
  ]
}
```

---

## 执行模式说明

ClawSwarm 支持 5 种任务执行模式：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `spawn` | 启动子龙虾（sub-agent）异步执行 | 大多数任务，并行化处理 |
| `fetch` | 抓取网页内容 | 搜索、数据采集 |
| `exec` | 直接执行 shell 命令 | 确定性系统操作 |
| `python` | 执行 Python 代码块 | 数据处理、脚本任务 |
| `workflow` | DAG 工作流（多步骤依赖） | 复杂多阶段任务 |

---

## 错误码

| 错误信息 | 说明 |
|---------|------|
| `prompt is required` | 缺少必填参数 `prompt` |
| `label is required` | 缺少必填参数 `label` |
| `node_id or relay_url is required` | 远程执行缺少节点标识 |
| `Node not found: xxx` | 节点未注册，需先调用 `clawswarm_remote_register` |
| `dead_letter module not available` | DLQ 模块缺失 |
| `health_scorer module not available` | 健康评分模块缺失 |
| `relay_client module not available` | Relay 客户端模块缺失 |
| `Monitor not available` | 监控服务未运行 |
