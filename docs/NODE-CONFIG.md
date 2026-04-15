# 节点配置指南

本文档说明如何配置 ClawSwarm 中的节点。

---

## 节点概述

ClawSwarm 中的每个节点都是一个独立的工作单元，具有以下属性：

- **node_id**：唯一标识符
- **capabilities**：能力标签列表
- **心跳**：定期更新存活状态

---

## 节点能力

| 能力标签 | 说明 | 适用任务类型 |
|----------|------|--------------|
| `search` | 网页搜索 | 调研、信息收集 |
| `analyze` | 数据分析 | 趋势分析、对比 |
| `report` | 报告写作 | 生成完整报告 |
| `write` | 文档写作 | 通用写作任务 |
| `code` | 代码执行 | 编程、脚本执行 |
| `read` | 文件读取 | 资料整理 |

---

## 启动节点

### 方式一：一键启动集群

```bash
python start_cluster.py
```

这会启动 3 个本地节点：
- claw_alpha（search + write + code）
- claw_beta（read + write）
- claw_gamma（search + analyze + report）

### 方式二：手动启动单个节点

```bash
python swarm_node.py <节点ID> [能力1] [能力2] ...

# 示例
python swarm_node.py my_node search write code
```

### 方式三：带自定义参数启动

```bash
# 设置轮询间隔为 3 秒
python swarm_node.py my_node search write --poll-interval 3

# 设置最大运行时间为 1 小时
python swarm_node.py my_node search write --max-runtime 3600
```

---

## 节点配置文件

节点心跳信息存储在 `agents/{node_id}.json`：

```json
{
  "node_id": "claw_alpha",
  "capabilities": ["search", "write", "code"],
  "status": "idle",
  "current_task_id": null,
  "last_heartbeat": "2026-04-15T17:45:00Z"
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `node_id` | 节点唯一标识 |
| `capabilities` | 能力标签列表 |
| `status` | 当前状态：`idle`, `busy`, `offline` |
| `current_task_id` | 正在执行的任务ID |
| `last_heartbeat` | 最后心跳时间 |

---

## 能力感知调度

主龙虾会根据任务类型自动分配给最合适的节点：

| 任务类型 | 所需能力 |
|----------|----------|
| `research` | search + (analyze/report) |
| `code` | code |
| `web_fetch` | search |
| `write` | write |
| `analyze` | analyze |

### 调度算法

```python
def assign_task(task_type, online_nodes):
    required = CAPABILITY_MAP.get(task_type, ["*"])
    
    if required == ["*"]:
        # 通用任务：选择最空闲的节点
        return min(online_nodes, key=lambda n: n.tasks_running)
    
    # 能力匹配：选择具备所需能力的节点
    candidates = [n for n in online_nodes 
                   if set(required).issubset(n.capabilities)]
    
    # 负载均衡：选择任务最少的
    return min(candidates, key=lambda n: n.tasks_completed)
```

---

## 全局节点配置

在 `swarm_config.json` 中管理节点注册：

```json
{
  "schema": "claw-swarm/v1",
  "version": "1.0.0",
  "nodes": {
    "claw_alpha": {
      "node_id": "claw_alpha",
      "capabilities": ["search", "write", "code"],
      "registered_at": "2026-04-14T13:56:48Z"
    },
    "claw_beta": {
      "node_id": "claw_beta",
      "capabilities": ["read", "write"],
      "registered_at": "2026-04-14T13:56:48Z"
    }
  }
}
```

---

## 节点故障处理

### 心跳超时

| 状态 | 超时时间 | 处理 |
|------|----------|------|
| `idle` | > 60s | 正常 |
| `stale` | > 120s | 任务可能已失败 |
| `offline` | > 300s | 节点离线，任务转移 |

### 故障恢复流程

```
1. 节点心跳超时（> 300s）
       ↓
2. 主龙虾检测到 offline 状态
       ↓
3. 查找该节点正在执行的任务
       ↓
4. 判断重试次数：
   - 未超限 → 放回队列重新分配
   - 已超限 → 标记为 failed
       ↓
5. 通知其他节点接管任务
```

---

## 自定义节点

### 创建自定义能力

在 `swarm_node.py` 中添加新的能力处理：

```python
CAPABILITY_HANDLERS = {
    "search": handle_search,
    "write": handle_write,
    "code": handle_code,
    "my_custom": handle_my_custom,  # 自定义能力
}

def handle_my_custom(task):
    # 自定义处理逻辑
    return {"result": "custom output"}
```

### 节点亲和性

某些任务可以指定偏好节点：

```json
{
  "id": "t_xxx",
  "type": "research",
  "preferred_node": "claw_alpha",
  "fallback_nodes": ["claw_beta", "claw_gamma"]
}
```

---

## 监控节点

### 查看所有节点

```bash
python swarm_scheduler.py status
```

### 查看特定节点

```bash
cat agents/claw_alpha.json
```

### 实时监控模式

```bash
python swarm_scheduler.py watch
```

这会每 10 秒刷新一次状态，显示：
- 在线节点及其心跳时间
- 当前执行中的任务
- 任务统计（pending/running/done/failed）
