# 任务格式规范

本文档详细说明 ClawSwarm 中任务文件的 JSON 格式。

---

## 任务文件位置

- **待执行任务**：`queue/t_{uuid}.json`
- **执行中任务**：`in_progress/t_{uuid}.json`
- **已完成任务**：`results/r_{uuid}.json`

---

## 完整任务格式

```json
{
  "id": "t_7b1df909df3a",
  "type": "research",
  "prompt": "搜索2026年最热门的AI项目",
  "description": "调研AI最新进展",

  "priority": 1,
  "status": "pending",
  "assigned_to": null,

  "created_at": "2026-04-15T12:00:00Z",
  "assigned_at": null,
  "started_at": null,
  "completed_at": null,

  "retry_count": 0,
  "max_retries": 3,
  "timeout_seconds": 300,

  "metadata": {
    "skill_required": "search",
    "result_format": "markdown"
  },

  "depends_on": null
}
```

---

## 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 任务唯一标识，格式：`t_{12位随机字符}` |
| `type` | string | ✅ | 任务类型：`research`, `code`, `web_fetch`, `write`, `general` |
| `prompt` | string | ✅ | 任务指令/提示词 |
| `description` | string | - | 简短描述（用于日志显示） |

| `priority` | int | - | 优先级，数字越大越优先，默认 1 |
| `status` | string | ✅ | 状态：`pending`, `running`, `done`, `failed` |
| `assigned_to` | string | - | 被分配的节点ID |

| `created_at` | ISO8601 | ✅ | 创建时间 |
| `assigned_at` | ISO8601 | - | 分配时间 |
| `started_at` | ISO8601 | - | 开始执行时间 |
| `completed_at` | ISO8601 | - | 完成时间 |

| `retry_count` | int | - | 已重试次数 |
| `max_retries` | int | - | 最大重试次数，默认 3 |
| `timeout_seconds` | int | - | 超时秒数，默认 300 |

| `metadata` | object | - | 扩展元数据 |
| `metadata.skill_required` | string | - | 所需技能标签 |
| `metadata.result_format` | string | - | 结果格式：`markdown`, `json`, `text` |

| `depends_on` | string/array | - | 依赖的任务ID |

---

## 任务类型

### 1. research（调研任务）

```json
{
  "id": "t_xxx",
  "type": "research",
  "prompt": "搜索AI Agent领域的最新进展",
  "metadata": {
    "skill_required": "search",
    "result_format": "markdown"
  }
}
```

**处理方式**：启动子 Agent 进行搜索调研

---

### 2. code（代码任务）

```json
{
  "id": "t_xxx",
  "type": "code",
  "prompt": "写一个Python脚本实现斐波那契数列",
  "metadata": {
    "skill_required": "code"
  }
}
```

**处理方式**：执行代码并返回结果

---

### 3. web_fetch（网页抓取）

```json
{
  "id": "t_xxx",
  "type": "web_fetch",
  "prompt": "抓取这篇博客的主要内容",
  "url": "https://example.com/blog/ai-trends",
  "metadata": {
    "skill_required": "web_fetch"
  }
}
```

**处理方式**：使用 web_fetch 工具抓取网页

---

### 4. write（写作任务）

```json
{
  "id": "t_xxx",
  "type": "write",
  "prompt": "写一篇关于AI的报告",
  "metadata": {
    "skill_required": "write",
    "result_format": "markdown"
  }
}
```

**处理方式**：调用写作 Agent 生成文档

---

### 5. general（通用任务）

```json
{
  "id": "t_xxx",
  "type": "general",
  "prompt": "执行一些操作",
  "description": "简单任务"
}
```

**处理方式**：默认处理逻辑

---

## 结果格式

任务完成后，结果存储在 `results/r_{task_id}.json`：

```json
{
  "task_id": "t_xxx",
  "status": "done",
  "node": "claw_alpha",
  "result": "调研结果：...\n\n1. 技术趋势\n2. 主流产品\n3. 未来展望",
  "completed_at": "2026-04-15T12:05:00Z"
}
```

失败时：

```json
{
  "task_id": "t_xxx",
  "status": "failed",
  "node": "claw_alpha",
  "error": "网络超时，无法连接到目标服务器",
  "failed_at": "2026-04-15T12:05:00Z"
}
```

---

## 创建任务

### 命令行方式

```bash
# 添加通用任务
python swarm_scheduler.py add "这是一个测试任务"

# 添加调研任务（自动分配给有 search 能力的节点）
python swarm_scheduler.py add "调研AI最新进展" --type research

# 添加高优先级任务
python swarm_scheduler.py add "紧急任务" --priority 10
```

### Python API 方式

```python
import json
import uuid
import os

def create_task(prompt, task_type="general", priority=1):
    task_id = f"t_{uuid.uuid4().hex[:12]}"
    task = {
        "id": task_id,
        "type": task_type,
        "prompt": prompt,
        "description": prompt[:50],
        "priority": priority,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "retry_count": 0,
        "max_retries": 3,
        "timeout_seconds": 300,
        "metadata": {}
    }
    
    queue_dir = r"D:\claw\swarm\queue"
    os.makedirs(queue_dir, exist_ok=True)
    
    with open(os.path.join(queue_dir, f"{task_id}.json"), "w") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    
    return task_id
```

---

## 任务依赖

支持任务依赖链（未来功能）：

```json
{
  "id": "t_003",
  "type": "write",
  "prompt": "基于调研结果写报告",
  "depends_on": ["t_001", "t_002"]
}
```

上述任务会等待 `t_001` 和 `t_002` 完成后才开始执行。
