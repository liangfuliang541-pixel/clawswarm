# ClawSwarm 架构设计文档
**版本：** v0.1  
**日期：** 2026-04-15  
**状态：** 设计中

---

## 一、设计目标

| 目标 | 说明 |
|------|------|
| **可靠性** | 任务不丢失，失败可重试，结果可追溯 |
| **可扩展性** | 同机→局域网→公网，渐进式扩展 |
| **透明性** | 任务状态全程可见，结果可查 |
| **容错性** | 节点挂了不影响整体，自动转移 |
| **简单性** | 零依赖安装，JSON文件即可驱动 |

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────────┐
│                      主龙虾 (Master)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │ 任务分发器 │  │ 结果聚合器 │  │ 健康监测  │  │ 策略调度 │ │
│  └────┬─────┘  └────▲─────┘  └────┬─────┘  └────┬─────┘ │
└───────┼────────────┼────────────┼────────────┼─────────┘
        │            │            │            │
        ▼            │            ▼            │
   ┌──────────────────────────────────────────┐          │
   │          共享存储层 (Shared Storage)       │          │
   │                                          │          │
   │   queue/         results/    agents/    logs/      │
   │   ┌─────┐        ┌─────┐      ┌─────┐   ┌─────┐    │
   │   │t_xxx│        │r_xxx│      │node1│   │t_xxx│    │
   │   │t_yyy│        │r_yyy│      │node2│   │t_yyy│    │
   │   │t_zzz│        │r_zzz│      │node3│   │     │    │
   │   └─────┘        └─────┘      └─────┘   └─────┘    │
   └──────────────────────────────────────────────────┘
        ▲            │            ▲
        │            │            │
┌───────┴────────────┴────────────┴─────────────────────┐
│                     节点龙虾 (Node 1~N)                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │ 任务轮询器 │  │ 执行引擎  │  │ 状态上报  │               │
│  └──────────┘  └──────────┘  └──────────┘               │
└─────────────────────────────────────────────────────────┘
```

---

## 三、核心模块设计

### 3.1 任务生命周期

```
  ┌────────┐    ┌────────────┐    ┌─────────────┐    ┌────────┐    ┌────────┐
  │ PENDING│───▶│ ASSIGNED   │───▶│ IN_PROGRESS │───▶│ DONE   │    │ FAILED │
  └────────┘    └────────────┘    └─────────────┘    └────────┘    └────────┘
                                     │                    ▲
                                     │                    │
                                     └────── max_retries ─┘
                                                      │
                                                 等待重试
```

**任务文件格式 (queue/t_xxx.json):**
```json
{
  "id": "t_xxx",
  "type": "research",
  "prompt": "搜索2026年最热门的AI项目",
  "priority": 1,
  "status": "IN_PROGRESS",
  "assigned_to": "node_01",
  "created_at": "2026-04-15T12:00:00Z",
  "assigned_at": "2026-04-15T12:01:00Z",
  "started_at": "2026-04-15T12:01:05Z",
  "retry_count": 0,
  "max_retries": 3,
  "timeout_seconds": 300,
  "metadata": {
    "skill_required": "web_search",
    "result_format": "markdown"
  }
}
```

### 3.2 节点心跳机制

**agents/{node_id}.json:**
```json
{
  "node_id": "node_01",
  "name": "小南同学-本地",
  "status": "online",
  "last_heartbeat": "2026-04-15T12:49:00Z",
  "capabilities": ["web_fetch", "exec", "file_write"],
  "current_task": "t_xxx",
  "task_started_at": "2026-04-15T12:45:00Z",
  "completed_tasks": 12,
  "failed_tasks": 1
}
```

**心跳检查策略：**
| 状态 | 条件 | 处理 |
|------|------|------|
| online | 心跳<60s | 正常 |
| stale | 60s<心跳<300s | 任务标记为ABANDONED，放回queue |
| offline | 心跳>300s | 从活跃列表移除，任务转移 |

### 3.3 任务分发策略

```python
# swarm_scheduler.py - 任务分配逻辑

def assign_task(task_id: str) -> Optional[str]:
    """选择最优节点分配任务"""
    nodes = load_online_nodes()

    # 策略1：负载最低优先
    candidates = [n for n in nodes if n.is_idle()]

    # 策略2：能力匹配
    task = load_task(task_id)
    if task.metadata.skill_required:
        candidates = [n for n in candidates
                      if task.metadata.skill_required in n.capabilities]

    if not candidates:
        return None  # 无可用节点，等待

    # 选择完成任务最多的（经验最丰富）
    best = min(candidates, key=lambda n: n.completed_tasks)
    return best.node_id
```

### 3.4 结果聚合

```python
# result_aggregator.py

def collect_results(task_ids: List[str]) -> dict:
    """收集所有任务结果"""
    results = []
    for tid in task_ids:
        rpath = f"results/r_{tid}.json"
        if exists(rpath):
            results.append(load_json(rpath))
        else:
            results.append({"id": tid, "status": "pending"})
    return {
        "total": len(task_ids),
        "completed": len([r for r in results if r.get("status") == "done"]),
        "results": results
    }
```

---

## 四、稳定性保障设计

### 4.1 任务防丢机制

```
1. 写入queue/    → 原子操作（先写.tmp再rename）
2. 节点poll      → rename queue/ → in_progress/
3. 节点完成      → 写 results/ → 删除 in_progress/
4. 节点崩溃      → 心跳检测 → in_progress/ → queue/（重新入队）
5. 主龙虾重启    → 扫描 in_progress/ → queue/
```

### 4.2 节点故障处理

```python
def handle_node_failure(node_id: str):
    """节点失联后的处理"""
    # 1. 标记节点为offline
    update_node_status(node_id, "offline")

    # 2. 找到该节点正在执行的任务
    abandoned = find_tasks_by_node(node_id, status="IN_PROGRESS")

    for task in abandoned:
        if task.retry_count >= task.max_retries:
            # 达到最大重试次数，标记失败
            update_task_status(task.id, "FAILED",
                             error=f"Node {node_id} failed after max retries")
        else:
            # 重置任务，放回队列
            reset_task(task.id)
            log(f"Task {task.id} returned to queue (node {node_id} offline)")

    # 3. 广播事件
    notify("node_offline", {"node_id": node_id, "affected_tasks": len(abandoned)})
```

### 4.3 超时与重试

```python
TASK_STATES = {
    "PENDING": {
        "timeout": None,      # 一直等待分配
        "on_timeout": None
    },
    "ASSIGNED": {
        "timeout": 60,        # 60s内必须开始执行
        "on_timeout": "return_to_queue"  # 放回队列重新分配
    },
    "IN_PROGRESS": {
        "timeout": 300,       # 5分钟超时
        "on_timeout": "increment_retry_and_requeue"
    }
}
```

---

## 五、模块清单与优先级

| 优先级 | 模块 | 状态 | 说明 |
|--------|------|------|------|
| P0 | 任务队列核心 | 待实现 | queue/results/in_progress目录+原子操作 |
| P0 | 节点注册+心跳 | 待实现 | agents/目录+心跳检测 |
| P0 | **修复poll_task路径bug** | **立即修复** | complete_task指向in_progress/ |
| P1 | 任务分发器 | 待实现 | assign_task + 策略选择 |
| P1 | 结果聚合器 | 待实现 | collect_results |
| P1 | 节点执行器 | 重写 | swarm_node.py 修复所有bug |
| P2 | 健康监测 | 待实现 | stale/offline检测+自动转移 |
| P2 | 错误恢复 | 待实现 | 节点崩溃后任务转移 |
| P3 | Web界面 | 可选 | 实时查看任务状态 |

---

## 六、立即要修的Bug清单

### Bug #1: complete_task路径错误（阻塞所有任务完成）

**文件：** `swarm_node.py`  
**问题：** `complete_task()` 从 `QUEUE_DIR` 读文件，但poll后文件已移到 `IN_PROGRESS_DIR`  
**修复：**
```python
# 修复前
task_file = os.path.join(QUEUE_DIR, f"{task_id}.json")

# 修复后
task_file = os.path.join(IN_PROGRESS_DIR, f"{task_id}.json")
```

### Bug #2: fail_task同样路径错误

同上，修复指向 `IN_PROGRESS_DIR`

### Bug #3: 节点心跳未实现

节点需要定时更新 `agents/{node_id}.json` 的 `last_heartbeat`

### Bug #4: 主龙虾不检测stale任务

主龙虾需要定期扫描 `in_progress/`，检测超时任务并重新入队

---

## 七、技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 通信 | 共享目录 + JSON文件 | 零依赖，跨平台，天然持久化 |
| 任务ID | UUID | 全局唯一，无冲突 |
| 原子性 | rename原子操作 | 防止并发写冲突 |
| 心跳 | 文件时间戳 | 无需额外服务 |
| 监控 | 日志文件 | 出现问题可追溯 |
| 扩展 | REST API（未来） | 跨公网时替换文件共享 |

---

## 八、目录结构

```
D:\claw\swarm\
├── swarm_config.json          # 全局配置
├── swarm_scheduler.py         # 主龙虾核心（任务分发+聚合+监控）
├── swarm_node.py              # 节点龙虾（轮询+执行+心跳）
├── swarm_utils.py             # 公共工具
│
├── queue/                     # 待执行任务
│   └── t_{uuid}.json
│
├── in_progress/               # 执行中任务
│   └── t_{uuid}.json          # 节点poll后rename至此
│
├── results/                   # 执行结果
│   └── r_{uuid}.json
│
├── agents/                    # 节点注册
│   └── {node_id}.json
│
└── logs/                      # 运行日志
    ├── scheduler.log
    └── node_{node_id}.log
```

---

## 九、实现路线图

```
Phase 1: 修复Bug + 跑通本地单节点
  ├─ 修复complete_task路径 ✅ (立即)
  ├─ 修复fail_task路径 ✅ (立即)
  ├─ 实现节点心跳 ✅
  ├─ 实现超时检测+任务回收 ✅
  └─ 本地单节点测试通过 ✅

Phase 2: 多节点本地协作
  ├─ 实现任务分发策略
  ├─ 实现结果聚合器
  ├─ 节点故障自动转移
  └─ 多节点并行测试

Phase 3: 跨机器协作
  ├─ 共享目录 → SMB/NFS
  └─ 或 REST API 模式

Phase 4: 产品化
  ├─ Web监控界面
  ├─ OpenClaw Skill封装
  └─ 错误告警通知
```

---

## 十、待讨论决策

1. **任务粒度：** 任务应该多细？一行命令还是一个复杂调研？
2. **节点能力：** 每个节点能力不同，如何表达和匹配？
3. **优先级：** 任务优先级如何影响分配顺序？
4. **结果格式：** 统一用JSON还是支持多格式？
5. **监控告警：** 任务失败/超时后如何通知？
