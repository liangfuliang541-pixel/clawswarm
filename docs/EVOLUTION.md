# ClawSwarm 进化蓝图 v2.0
**版本：** v2.0  
**日期：** 2026-04-15  
**状态：** 架构设计  
**愿景：** 从「共享文件夹脚本」进化为「企业级多Agent协同平台」

---

## 一、现状诊断

### 1.1 当前架构（v0.1）✅ 已实现

```
本地单节点
├── swarm_scheduler.py   ✅ 主调度（任务创建+状态查询+回收）
├── swarm_node.py        ✅ 节点客户端（原子poll+心跳+结果写入）
├── queue/               ✅ 待执行
├── in_progress/        ✅ 执行中（原子rename保护）
├── results/            ✅ 结果存储
└── agents/             ✅ 节点心跳
```

**已跑通：** 本地单节点任务完整生命周期（add→poll→execute→done）

### 1.2 当前6大能力缺口 ❌

| 缺口 | 影响 |
|------|------|
| 无任务执行能力 | execute_task() 只是占位符，无法真正工作 |
| 无多节点协作 | 3个节点都只轮询，没有分工 |
| 无任务依赖图 | 无法表达"任务A完成后才能做任务B" |
| 无跨机器通信 | 无法连接云服务器上的龙虾 |
| 无智能调度 | 只是轮询，不懂能力匹配 |
| 无结果聚合 | 多个子任务完成后无法自动汇总 |

### 1.3 核心矛盾

```
当前设计：轮询驱动（Pull）
问题：节点不知道自己擅长什么，master不知道节点在做什么

未来设计：事件驱动 + 智能调度（Push + Observe）
优势：任务精准分配，状态实时感知
```

---

## 二、愿景：三层进化路径

```
Phase 1              Phase 2              Phase 3
"能用"              "好用"               "产品级"
─────────────────   ──────────────────   ──────────────────
本地多节点           局域网多机器          云端+公网
单一体验             共享存储              REST API
轮询驱动             事件通知              WebSocket推送
手动聚合             半自动聚合            全自动流水线
```

---

## 三、Phase 1 — 多节点协作（本周目标）

### 3.1 问题：当前多节点只是"抢任务"，没有分工

现有3个节点都在轮询同一队列，能力各不相同：
- claw_alpha: search + write + code
- claw_beta: read + write
- claw_gamma: search + analyze + report

**问题：** 调研任务被beta抢走了，但它不会搜索。code任务被gamma抢了，但它不会写代码。

### 3.2 解决方案：能力感知调度

```python
# swarm_scheduler.py 新增：智能任务分配

CAPABILITY_MAP = {
    "web_fetch":    ["search", "web_fetch"],
    "research":     ["search", "analyze", "report"],
    "code":         ["code", "write"],
    "file_write":   ["write"],
    "file_read":    ["read"],
    "general":      ["*"],           # 通用节点，什么都能接
}

def assign_task_to_best_node(task: dict) -> Optional[str]:
    """根据任务类型匹配合适节点"""
    task_type  = task.get("type", "general")
    required   = CAPABILITY_MAP.get(task_type, ["*"])

    online = load_online_nodes()

    if required == ["*"]:
        # 通用任务：选最空闲的
        candidates = online
    else:
        # 能力匹配：节点必须具备全部所需能力
        candidates = [
            n for n in online
            if set(required).issubset(set(n.get("capabilities", [])))
        ]

    if not candidates:
        return None  # 无合适节点，等待

    # 负载均衡：选任务最少的
    return min(candidates, key=lambda n: n.get("completed_tasks", 0))["node_id"]
```

### 3.3 解决方案：主龙虾主动推送任务（Push模式）

当前是 Pull（节点主动轮询），改为 Push（主龙虾分配后通知节点）：

```python
# 方式A：节点订阅自己的任务文件
# 节点watch "queue/{node_id}_assigned/" 目录

# 方式B：主龙虾直接通知（未来REST API）
# POST http://node:port/assign {"task": {...}}

# 方式C（Phase 1 最简单）：标记分配 + 节点按能力过滤poll
```

**Phase 1 采用方式C的改进版：** 在 poll_task 中加入能力过滤 + 任务分配标记

```python
def poll_task(node_id, capabilities):
    """只抢被分配给自己的任务，或者未被分配的通用任务"""
    for fname in sorted(os.listdir(QUEUE_DIR)):
        task = read_json(fpath)
        assigned_to = task.get("assigned_to")
        task_type   = task.get("type", "general")

        # 规则1：任务明确分配给当前节点
        if assigned_to == node_id:
            return try_acquire(fname, node_id)

        # 规则2：任务未分配，且节点有相应能力
        if assigned_to is None:
            if can_handle(task_type, capabilities):
                task["assigned_to"] = node_id  # 先占住
                return try_acquire(fname, node_id)
        continue
    return None
```

### 3.4 Phase 1 任务清单

| 优先级 | 任务 | 状态 |
|--------|------|------|
| P0 | 能力感知调度 | ✅ 已完成 |
| P0 | 主龙虾 add_task 时分配节点 | ✅ 已完成 |
| P0 | execute_task 接入真实能力 | ✅ 已完成（fetch/exec/python/spawn） |
| P1 | 多节点并行测试 | ✅ 已完成（84 tests） |
| P1 | 任务依赖链（后续任务A完成后触发B） | ✅ 已完成（DAG orchestrator） |
| P1 | MCP Server 协议通信 | ✅ 已完成（v0.8.0，6 tools） |
| P1 | Web Dashboard 监控面板 | ✅ 已完成（v0.8.0，FastAPI + WebSocket） |
| P1 | GitHub Actions CI/CD | ✅ 已完成（v0.8.0） |
| P2 | 节点能力注册时自检 | ✅ 已完成 |
| P2 | OpenClaw Skill 集成 | ✅ 已完成（v0.7.0） |

---

## 四、Phase 2 — 局域网多机器（2-4周目标）

### 4.1 架构演进

```
当前：同一台机器，同一个目录
         D:\claw\swarm\

Phase 2：局域网，多台机器，共享目录
                    ┌── SMB/UNC路径 ──┐
  主龙虾 ──────────▶│  \\192.168.x.x\swarm │◀─── 节点A, 节点B, 节点C
                    └─────────────────┘
```

**方案A：SMB共享（最简单）**
```python
BASE_DIR = r"\\192.168.1.100\swarm"   # 主服务器的共享目录
```
- 优点：零代码改造，目录结构不变
- 缺点：需要同一局域网，文件锁性能差
- 适用：家庭/办公室局域网

**方案B：REST API（推荐）**
```python
# 每个节点运行一个轻量HTTP服务
# 主龙虾通过HTTP请求推送任务

NodeAPI:
  POST /poll          → 获取分配给自己的任务
  POST /complete      → 提交结果
  GET  /status        → 健康检查
  GET  /heartbeat     → 心跳上报
```

### 4.2 节点HTTP服务（swarm_node_api.py）

```python
# swarm_node_api.py — 节点侧HTTP服务
from flask import Flask, request, jsonify

app = Flask(__name__)
LOCAL_QUEUE = r"D:\claw\swarm\node_local_queue"

@app.route("/poll", methods=["POST"])
def poll():
    node_id = request.json.get("node_id")
    task = find_local_task(node_id)
    if task:
        mark_in_progress(task["id"])
        return jsonify({"status": "ok", "task": task})
    return jsonify({"status": "no_task"})

@app.route("/complete", methods=["POST"])
def complete():
    task_id  = request.json["task_id"]
    result   = request.json["result"]
    save_result(task_id, result)
    notify_master(task_id, result)   # 通知主龙虾
    return jsonify({"status": "ok"})

app.run(host="0.0.0.0", port=5171)
```

### 4.3 主龙虾API服务（swarm_master_api.py）

```python
# swarm_master_api.py — 主龙虾HTTP服务（供Web界面/其他系统调用）
@app.route("/tasks", methods=["POST"])       # 创建任务
@app.route("/tasks", methods=["GET"])        # 列表
@app.route("/tasks/<id>", methods=["GET"])   # 详情
@app.route("/tasks/<id>/result", methods=["GET"])  # 结果
@app.route("/nodes", methods=["GET"])        # 节点列表
@app.route("/nodes/<id>", methods=["GET"])   # 节点详情
```

---

## 五、Phase 3 — 云端 + 公网（未来目标）

### 5.1 最终架构

```
┌─────────────────────────────────────────────────────────────┐
│                      控制平面 (Control Plane)                │
│                                                             │
│   主龙虾 (Master Agent)                                      │
│   ├── 任务编排引擎 (Orchestration Engine)                   │
│   ├── 智能调度器 (Smart Scheduler)                          │
│   ├── 结果聚合器 (Result Aggregator)                        │
│   ├── 监控仪表盘 (Monitoring Dashboard)                     │
│   └── Web API (REST + WebSocket)                           │
│                                                             │
│   存储层                                                     │
│   ├── 任务队列 (Redis/RabbitMQ)                             │
│   ├── 结果存储 (PostgreSQL + S3)                            │
│   └── 节点注册表 (Consul/etcd)                              │
└─────────────────────────────────────────────────────────────┘
        ▲                  ▲                  ▲
        │                  │                  │
        │ HTTP/WebSocket   │                  │
        │                  │                  │
┌───────┴───────┐  ┌──────┴──────┐  ┌───────┴───────┐
│ 节点龙虾(云)    │  │ 节点龙虾(本地) │  │ 节点龙虾(手机)  │
│ claw_alpha    │  │ claw_beta    │  │ claw_gamma   │
│ 腾讯云服务器    │  │ 办公室电脑    │  │ Android平板   │
└───────────────┘  └─────────────┘  └───────────────┘
```

### 5.2 任务编排引擎（核心差异化能力）

**这是 ClawSwarm 的核心竞争力。** 比现有开源方案（crewAI、AutoGen）更强的点：

```python
# 用户只需要描述目标，系统自动拆解 + 分配 + 执行 + 汇总

用户说：
"帮我调研AI Agent领域的最新进展，包括：
 1. 技术趋势（搜索+分析）
 2. 主流产品对比（搜索+整理）
 3. 生成一份报告（写报告）
"

ClawSwarm 自动拆解为：
TaskGraph:
  task_001 [research_tech]  → claw_alpha (search+analyze)
  task_002 [research_product] → claw_beta (search+write)
  task_003 [write_report]   → claw_gamma (report)
                               ↑
                    依赖 task_001 + task_002 的结果

执行流程：
  并行: task_001 ═══════════╗
  并行: task_002 ═══════════╝
           ↓ (两者都完成)
  串行: task_003 [汇总输出]
```

**任务依赖图 DSL：**

```python
from swarm import Task, TaskGraph, Node

# 定义任务图
graph = TaskGraph()

graph.add("search_news",
    prompt="搜索AI Agent最新进展",
    type="research",
    nodes=["claw_alpha"]          # 能力要求
)

graph.add("analyze_news",
    prompt="分析收集到的信息",
    type="analyze",
    depends_on=["search_news"]    # 依赖搜索任务
)

graph.add("write_report",
    prompt="撰写完整报告",
    type="report",
    depends_on=["analyze_news"]   # 依赖分析任务
)

# 一键启动
result = graph.execute()
print(result["write_report"]["content"])
```

---

## 六、关键技术决策

### 6.1 消息队列选型

| 方案 | 优点 | 缺点 | 适用阶段 |
|------|------|------|----------|
| 共享目录+文件 | 零依赖，稳定 | 无实时通知，延迟高 | Phase 1 ✅ |
| Redis Pub/Sub | 实时，低延迟 | 需安装Redis | Phase 2 |
| RabbitMQ | 功能丰富，支持重试 | 部署复杂 | Phase 3 |
| SQLite + polling | 简单，SQL查询 | 并发差 | Phase 1过渡 |

### 6.2 节点注册方式

| 方式 | 优点 | 缺点 |
|------|------|------|
| 配置文件 | 简单 | 无法动态发现 |
| 心跳注册 | 动态，感知存活 | 需要节点主动上报 |
| mDNS/DNS-SD | 自动发现局域网节点 | 跨网段困难 |

**决策：Phase 1 用心跳注册（已有），Phase 2 保留，Phase 3 加 mDNS 自动发现**

### 6.3 任务分配策略

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| 轮询（Round Robin） | 轮流分配 | 节点能力相同 |
| 能力匹配 | 按技能分配 | 节点能力不同 ✅ |
| 负载均衡 | 选最空闲的 | 节点能力不同 ✅ |
| 亲和性 | 优先同一节点（利用缓存） | 有关联的任务 |
| 优先级 | 紧急任务优先分配 | 有SLA要求 |

**决策：Phase 1 实现「能力匹配 + 负载均衡」，Phase 2 加「亲和性」**

### 6.4 结果聚合策略

```python
# 自动判断聚合方式
def aggregate_results(task_ids: List[str]) -> dict:
    results = [load_result(tid) for tid in task_ids]

    if len(results) == 1:
        return results[0]  # 单结果直接返回

    # 判断聚合方式
    types = [r.get("type") for r in results]

    if all(t in ("research", "analysis") for t in types):
        # 并行调研 → 合并所有发现
        return {
            "summary": merge_text_results(results),
            "sources": merge_sources(results),
        }

    if all(t in ("write", "report") for t in types):
        # 多段写作 → 按顺序拼接
        return {"content": concat_in_order(results)}

    # 默认：列表
    return {"results": results}
```

---

## 七、OpenClaw 深度集成

这是 ClawSwarm 相比其他框架的独特优势——直接跑在 OpenClaw 生态上。

### 7.1 主龙虾 = OpenClaw Agent

```
用户消息 → OpenClaw Agent（主龙虾）
          ↓ 分析用户请求
          ↓ 拆解为任务
          ↓ 写入 swarm/queue/
          ↓ 监控节点状态
          ↓ 聚合结果
          ↓ 返回给用户
```

**OpenClaw Skill 封装：**
```
/swarm add "调研AI最新进展"  → 写入队列，返回 task_id
/swarm status               → 查询状态
/swarm result <task_id>     → 获取结果
/swarm graph                → 查看任务依赖图
/swarm node add <name>      → 注册新节点
/swarm watch                → 实时监控
```

### 7.2 节点龙虾 = OpenClaw sessions_spawn

```python
# swarm_node.py 的 execute_task() 接入真实能力

def execute_task(task):
    task_type = task["type"]

    if task_type == "research":
        # 使用 sessions_spawn 启动子Agent做调研
        sub = sessions_spawn(
            task="搜索：{}".format(task["prompt"]),
            runtime="acp",
            agentId="research-agent",
            mode="run"
        )
        return sub.result

    elif task_type == "code":
        # 直接 exec 执行代码
        return exec_python(task["prompt"])

    elif task_type == "web_fetch":
        # 调用 web_fetch 工具
        return web_fetch(task["url"])

    elif task_type == "file_write":
        # 写文件
        return write_file(task["path"], task["content"])

    else:
        return generic_agent_execute(task)
```

---

## 八、产品化路线（面向未来销售）

### 8.1 开源策略

```
开源版本（AGPL）：
  - 单机版完整功能
  - 局域网多节点
  - 基础任务编排

商业授权（闭源需付费）：
  - 云端版（无公网IP也能用）
  - Web界面
  - 高级编排DSL
  - 技术支持
```

### 8.2 竞争壁垒

| 维度 | crewAI/AutoGen | ClawSwarm |
|------|----------------|-----------|
| 部署难度 | 需要写Python代码 | JSON文件即可驱动 |
| 多机器协同 | 不支持 | 共享目录零配置 |
| 断网容错 | 不支持 | 本地队列，不丢任务 |
| OpenClaw集成 | 无 | 深度集成，可语音控制 |
| 监控界面 | 有Web界面 | Phase 3才有 |

### 8.3 MVP定义（先跑通再开源）

```
MVP验收标准：
□ 一台机器 + 2个节点 并行执行任务
□ 节点按能力分配（alpha做搜索，beta做写作）
□ 任务失败后自动重试（最多3次）
□ 主龙虾重启后能恢复 in_progress 中的任务
□ Web界面可查看任务状态（Phase 2）
□ OpenClaw Skill 一句话创建任务
```

---

## 九、近2周开发计划

### Week 1：核心能力

```
Day 1-2：能力感知调度
  - 重写 add_task：根据 type 自动分配节点
  - poll_task 加能力过滤
  - 测试：alpha接搜索任务，beta写作

Day 3-4：execute_task 接入真实能力
  - 接入 web_fetch（网页抓取）
  - 接入 sessions_spawn（子Agent调研）
  - 接入 write_file（结果写入）
  - 端到端测试：创建调研任务→节点执行→结果聚合

Day 5：多节点并行测试
  - 3节点同时运行
  - 验证能力匹配
  - 验证结果不冲突
```

### Week 2：可靠性 + 局域网

```
Day 6-7：超时与重试完善
  - recover_stale_tasks 上线
  - 节点崩溃模拟测试
  - 验证任务不丢失

Day 8-9：局域网部署
  - SMB共享目录配置
  - 云服务器节点接入
  - 跨机器通信验证

Day 10：监控 + 文档
  - swarm_scheduler.py watch 模式
  - README + 使用文档
```

---

## 十、待讨论决策

| 问题 | 选项A | 选项B | 推荐 |
|------|-------|-------|------|
| 消息队列 | 保持文件（简单） | Redis（实时） | Phase 1: 文件，Phase 2: Redis |
| 任务分配 | 主龙虾推送 | 节点拉取 | Phase 1: 拉取+过滤，Phase 2: 推送 |
| 跨机器通信 | SMB共享 | REST API | Phase 2: SMB，Phase 3: REST |
| 开源时机 | MVP完成后 | 现在 | MVP完成后 |
| 商业授权 | AGPL+闭源例外 | 双许可证 | AGPL+商业例外 |
