# Phase2 设计草案 — 局域网多节点协作
**版本：** v0.1-draft  
**日期：** 2026-04-16  
**状态：** 设计中  
**作者：** Agent C

---

## 一、目标

在 Phase1 本地单节点基础上，扩展为**局域网多节点协作**：

1. 多台机器通过 SMB/CIFS 共享同一个 `swarm_data/` 目录
2. REST API 支持同步/异步任务提交 + Webhook 回调
3. 多 OpenClaw 实例共享同一个任务队列（去中心化协调）

---

## 二、架构图（文本）

```
┌─────────────────────────────────────────────────────────────────┐
│                      局域网 (LAN)                               │
│                                                                 │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│   │  Windows PC  │    │  Linux Server │    │  Mac Dev     │   │
│   │  192.168.1.10│    │  192.168.1.20 │    │  192.168.1.30│   │
│   │              │    │              │    │              │   │
│   │  OpenClaw A  │    │  OpenClaw B  │    │  OpenClaw C  │   │
│   │  (master)    │    │  (worker)    │    │  (worker)    │   │
│   │  Dashboard   │    │              │    │              │   │
│   │  REST API    │    │              │    │              │   │
│   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘   │
│          │                   │                   │            │
│          │   SMB/CIFS 共享目录 (swarm_data/)      │            │
│          └───────────────────┼───────────────────┘            │
│                              ▼                                 │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │  共享存储 (NAS / Windows 共享 / Linux NFS)              │  │
│   │  ───────────────────────────────────────────────────  │  │
│   │  swarm_data/                                           │  │
│   │    queue/t_*.json       ← 任务队列                      │  │
│   │    in_progress/t_*.json ← 正在执行                      │  │
│   │    results/r_*.json     ← 执行结果                      │  │
│   │    agents/*.json        ← 节点注册                      │  │
│   │    locks/               ← 文件锁                        │  │
│   │    webhooks/            ← Webhook 回调队列              │  │
│   └─────────────────────────────────────────────────────────┘  │
│                              ▲                                 │
│                              │                                 │
│   ┌──────────────────────────┴──────────────────────────────┐  │
│   │              任务分发层 (Task Distributor)               │  │
│   │  策略：能力匹配 + 负载最低 + 心跳健康检测                 │  │
│   └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

─── 公网扩展路径 ───────────────────────────────────────────────────
  REST API  →  Webhook  →  消息队列（Redis/RabbitMQ）→  云端节点
```

---

## 三、关键技术选型

### 3.1 SMB 共享方案

| 方案 | 库 | 优点 | 缺点 |
|------|-----|------|------|
| **smbprotocol** ✅ | `smbprotocol` (pure Python) | 跨平台（Win/Mac/Linux），无需 C 依赖，Python 3.8+ | 文档较少，社区较小 |
| pysmb | `pysmb` (python-smbc) | 老牌成熟 | 需要 libsmb C 库，Windows 上难装 |
| smbprotocol-ng | `smbprotocol-ng` | 活跃开发中 | 太新，生产环境风险 |
| NFS | `nfs-utils` | Linux 间高速共享 | Windows 原生不支持，需要第三方客户端 |

**推荐：`smbprotocol`**（pure Python，pip install smbprotocol）

共享目录挂载方案：
```bash
# Windows → 挂载 NAS 共享
net use Z: \\192.168.1.254\swarm_data /user:admin password

# Linux → 挂载 Windows 共享
sudo mount -t cifs //192.168.1.10/swarm_data /mnt/swarm_data \
  -o username=admin,password=xxx,vers=3.0

# macOS → 挂载
mount_smbfs //admin:password@192.168.1.254/swarm_data /Volumes/swarm_data
```

路径统一策略：
```python
# paths.py 添加 SMB 配置
SMB_MOUNT_POINT = os.environ.get("CLAWSWARM_SMB_MOUNT", None)
# 如果配置了 SMB 挂载点，使用挂载点作为 BASE_DIR
# 否则回退到本地 swarm_data/
```

### 3.2 REST API 增强

#### 同步 + 异步任务提交

```python
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

app = FastAPI()

class TaskSubmit(BaseModel):
    description: str
    mode: str = "spawn"          # spawn | mcporter | direct
    sync: bool = False           # True = 同步等待结果
    webhook_url: str | None = None
    timeout_seconds: int = 300

@app.post("/api/tasks")
async def submit_task(task: TaskSubmit, background: BackgroundTasks):
    # 写入队列
    task_id = write_task_to_queue(task)
    
    if task.sync:
        # 同步模式：轮询等待结果文件
        result = await wait_for_result(task_id, timeout=task.timeout_seconds)
        return {"task_id": task_id, "status": "done", "result": result}
    else:
        # 异步模式：立即返回 task_id
        # 如果配置了 webhook，启动后台任务完成时通知
        if task.webhook_url:
            background.add_task(notify_webhook, task_id, task.webhook_url)
        return {"task_id": task_id, "status": "pending"}
```

#### Webhook 回调机制

```python
# webhook.py
import aiohttp

async def notify_webhook(task_id: str, webhook_url: str, result: dict):
    """任务完成时主动回调通知"""
    payload = {
        "event": "task_completed",
        "task_id": task_id,
        "status": result.get("status"),
        "result": result,
        "timestamp": datetime.now().isoformat(),
    }
    async with aiohttp.ClientSession() as session:
        for attempt in range(3):
            try:
                async with session.post(webhook_url, json=payload, timeout=10) as resp:
                    if resp.status < 400:
                        return
            except Exception:
                await asyncio.sleep(2 ** attempt)  # 指数退避
```

### 3.3 多节点协调

#### 方案 A：文件系统锁（Phase2 早期）

适合节点数 ≤ 5 的局域网场景。

```python
# locks.py — 基于文件锁的多节点协调
import filelock

LOCK_DIR = Path(BASE_DIR) / "locks"
LOCK_DIR.mkdir(exist_ok=True)

def acquire_lock(lock_name: str, timeout: int = 30) -> filelock.FileLock:
    lock_path = LOCK_DIR / f"{lock_name}.lock"
    lock = filelock.FileLock(str(lock_path), timeout=timeout)
    lock.acquire()
    return lock

def release_lock(lock: filelock.FileLock):
    lock.release()

# 使用方式：任务分发时的原子性保护
with acquire_lock(f"assign_task", timeout=10):
    task = find_best_available_task()
    mark_task_assigned(task.id, node_id)
```

问题：filelock 在 NFS 上不可靠（需要 `fcntl`），SMB 不支持 `fcntl`。

#### 方案 B：Redis（Phase2 成熟期）✅

适合多节点、跨网段、需要 pub/sub 通知的场景。

```python
# redis_coordinator.py
import redis, json

r = redis.Redis(host="192.168.1.254", port=6379, db=0)

# ── 任务队列（Redis List）─────────────────────────
def enqueue_task(task: dict):
    r.lpush("clawswarm:queue", json.dumps(task))

def dequeue_task(node_id: str, timeout: int = 30) -> dict | None:
    # BRPOP 阻塞直到有任务或超时
    result = r.brpop("clawswarm:queue", timeout=timeout)
    if result:
        task = json.loads(result[1])
        task["assigned_to"] = node_id
        r.hset(f"clawswarm:task:{task['id']}", mapping=task)
        return task
    return None

def update_task_status(task_id: str, status: str, result: dict = None):
    r.hset(f"clawswarm:task:{task_id}", "status", status)
    if result:
        r.hset(f"clawswarm:task:{task_id}", "result", json.dumps(result))
    # 发布状态变化事件
    r.publish(f"clawswarm:events", json.dumps({
        "type": "task_status_change",
        "task_id": task_id, "status": status
    }))

# ── 节点心跳（Redis Hash + ZSet）──────────────────
def register_node(node_id: str, capabilities: list):
    r.hset("clawswarm:nodes", node_id, json.dumps({
        "capabilities": capabilities,
        "registered_at": datetime.now().isoformat()
    }))
    r.zadd("clawswarm:heartbeat", {node_id: time.time()})

def heartbeat(node_id: str):
    r.zadd("clawswarm:heartbeat", {node_id: time.time()})

def get_online_nodes(max_stale_seconds: int = 60) -> list:
    cutoff = time.time() - max_stale_seconds
    stale = r.zrangebyscore("clawswarm:heartbeat", cutoff, "+inf")
    return [n.decode() for n in stale]
```

Redis 优势：
- 原子操作（LPUSH/BRPOP）天然解决任务抢占冲突
- Pub/Sub 实现节点间事件通知（无需轮询）
- Hash 存储节点状态，ZSet 做心跳排序
- 支持 Key 过期（TTL）自动清理僵尸任务

---

## 四、实现步骤

### Step 1: SMB 共享目录集成（约 2 天）

1. 研究 `smbprotocol` 库，编写 `smb_share.py` 挂载工具
2. 修改 `paths.py`：检测 `CLAWSWARM_SMB_MOUNT` 环境变量，优先使用 SMB 路径
3. 在局域网两台机器上测试文件读写一致性
4. 验证 rename 原子操作在 SMB 上正常（避免并发冲突）

### Step 2: REST API 增强 + Webhook（约 2 天）

1. 在 `dashboard/dashboard.py` 中增加 `/api/tasks/sync` 端点
2. 实现 `BackgroundTasks` 处理 Webhook 回调（带重试+指数退避）
3. 任务状态变更自动触发 Webhook（`task_completed` / `task_failed`）
4. 用 `pytest` 写 Webhook 回调测试（mock HTTP server）

### Step 3: 多节点协调（Redis）（约 3 天）

1. 部署 Redis（`docker run -d -p 6379:6379 redis`）
2. 实现 `redis_coordinator.py`：队列、心跳、节点发现
3. 修改 `spawn_manager.py` 和 `orchestrator.py` 使用 Redis 协调
4. 验证多节点同时 poll 同一个任务不会重复执行（原子性测试）

### Step 4: Dashboard 集成测试（约 1 天）

1. 启动多个 OpenClaw 实例（不同节点 ID）
2. 通过 Dashboard WebSocket 提交任务
3. 验证任务分发到不同节点
4. 验证 Webhook 收到完成通知

### Step 5: 故障测试 + 文档（约 1 天）

1. 杀掉一个节点，验证任务自动重新入队
2. 写 `DEPLOY_LAN.md` 局域网部署指南
3. 更新 `ARCHITECTURE.md` 中的 Phase2 架构图

---

## 五、潜在风险

| 风险 | 概率 | 影响 | 缓解方案 |
|------|------|------|----------|
| SMB rename 不是原子操作 | 中 | 高 | 使用 Redis 原子命令替代文件 rename |
| NFS 文件锁不可靠 | 中 | 高 | 切换到 Redis 分布式锁 |
| 多节点并发写同一结果文件 | 低 | 高 | 使用 `{node_id}_{task_id}.json` 命名 |
| Webhook 回调失败（网络问题） | 高 | 中 | 持久化重试队列（webhooks/pending/） |
| Redis 单点故障 | 中 | 高 | Redis Sentinel 或 Redis Cluster |
| Windows SMB 共享性能差 | 低 | 低 | 启用 SMB 3.0，多线程批量写 |
| 节点能力描述与实际不符 | 中 | 中 | 心跳时上报实际能力，定期重新探测 |

---

## 六、目录结构变更

```
swarm_data/
├── queue/
├── in_progress/
├── results/
├── agents/
├── locks/              ← 新增：文件系统锁（Phase2 早期）
│   └── *.lock
├── webhooks/           ← 新增：Webhook 重试队列
│   └── pending/
│       └── wh_{uuid}.json
├── redis/              ← 未来（Redis 数据持久化可选）
└── smb_cache/          ← 未来（ SMB 远程文件本地缓存）
```

---

## 七、依赖变更

```txt
# 新增 Phase2 依赖
smbprotocol>=1.10.0       # SMB/CIFS 共享（跨平台）
redis>=5.0.0              # 多节点协调
filelock>=3.12.0          # 文件系统锁（Phase2 早期降级）
aiohttp>=3.9.0            # Webhook HTTP 回调
pydantic>=2.0             # REST API 数据验证
```
