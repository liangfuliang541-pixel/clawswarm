# ClawSwarm Architecture - Modular Design

English | [中文](ARCHITECTURE_CN.md)

> "Skills are bricks. Architecture is the building."

---

## 🏗️ Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ClawSwarm Cluster                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    LAYER 3: Orchestration (编排层)                   │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │   │
│  │  │   Master    │  │  Scheduler  │  │  Aggregator │                 │   │
│  │  │   Agent     │  │   (Task)    │  │  (Result)   │                 │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    LAYER 2: Execution (执行层)                      │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │   │
│  │  │   Agent     │  │   Agent     │  │   Agent     │   ...            │   │
│  │  │  (OpenClaw) │  │  (OpenClaw) │  │  (OpenClaw) │                 │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    LAYER 1: Capability (能力层)                     │   │
│  │                                                                      │   │
│  │   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         │   │
│  │   │  Skill   │  │   MCP    │  │  Tool    │  │  Model   │         │   │
│  │   │          │  │  Server   │  │  (exec)  │  │  (LLM)   │         │   │
│  │   └──────────┘  └──────────┘  └──────────┘  └──────────┘         │   │
│  │                                                                      │   │
│  │   Example Skills: web_search, browser, email, wechat               │   │
│  │   Example MCP: notion, slack, github, database                      │   │
│  │   Example Tools: exec, file_read, websocket                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔷 Layer 1: Capability Layer (能力层)

The foundation - what capabilities each node CAN provide.

```
Capability Layer
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                        SKILLS (技能)                             │  │
│   │  OpenClaw 内置能力，每个 skill = 一个 specialized workflow      │  │
│   ├─────────────────────────────────────────────────────────────────┤  │
│   │  Category     │  Skill Name      │  Description                │  │
│   │  ─────────────┼──────────────────┼───────────────────────────── │  │
│   │  🌐 Web       │  web_search      │  搜索互联网                  │  │
│   │               │  web_fetch       │  获取网页内容                │  │
│   │               │  browser         │  浏览器自动化                │  │
│   │  📧 Comm      │  email-skill     │  邮件收发                    │  │
│   │               │  wechat          │  微信消息                    │  │
│   │  📄 Doc       │  docx            │  Word 文档                   │  │
│   │               │  pdf             │  PDF 处理                    │  │
│   │               │  xlsx            │  Excel 表格                  │  │
│   │  🖼️ Media     │  canvas-design   │  设计绘图                   │  │
│   │  🧮 Data      │  neodata         │  金融数据查询                │  │
│   │  📅 Schedule  │  wecom-schedule  │  日程管理                    │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                     MCP Servers (MCP 服务)                      │  │
│   │  Model Context Protocol - 标准化外部服务集成                    │  │
│   ├─────────────────────────────────────────────────────────────────┤  │
│   │  MCP Name       │  Capabilities                               │  │
│   │  ───────────────┼───────────────────────────────────────────── │  │
│   │  github         │  issues, pr, repo management                │  │
│   │  slack          │  send message, channel management           │  │
│   │  notion         │  page, database CRUD                        │  │
│   │  database       │  SQL query, data manipulation               │  │
│   │  filesystem     │  file CRUD, directory management             │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                     TOOLS (底层工具)                             │  │
│   │  OpenClaw 内置工具，不依赖 skill                                 │  │
│   ├─────────────────────────────────────────────────────────────────┤  │
│   │  Tool Name      │  Description                                 │  │
│   │  ───────────────┼───────────────────────────────────────────── │  │
│   │  exec           │  执行 Shell 命令                             │  │
│   │  sessions_spawn │  启动子 Agent 会话                          │  │
│   │  sessions_send  │  向 Agent 发送消息                          │  │
│   │  file_read      │  读取文件                                    │  │
│   │  file_write     │  写入文件                                    │  │
│   │  message        │  发送消息到各渠道                            │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🔷 Layer 2: Execution Layer (执行层)

Each Node runs an OpenClaw Agent that combines capabilities.

```
Execution Layer - Per Node
┌────────────────────────────────────────────────────────────────────────┐
│                         Node Agent (OpenClaw)                         │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐  │
│   │  Agent Config                                                   │  │
│   │  ┌──────────────────────────────────────────────────────────┐  │  │
│   │  │  agent_id: "claw_alpha"                                  │  │  │
│   │  │  model: "qclaw/modelroute"                               │  │  │
│   │  │  capabilities: ["search", "write", "code", "browser"]  │  │  │
│   │  │  skills: ["web-search", "browser", "docx", "pdf"]       │  │  │
│   │  │  mcp_servers: ["github", "slack"]                      │  │  │
│   │  └──────────────────────────────────────────────────────────┘  │  │
│   └────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│   ┌────────────────────────────────────────────────────────────────┐  │
│   │  Task Execution Pipeline                                       │  │
│   │                                                                   │  │
│   │   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  │  │
│   │   │ Receive  │──▶│  Plan    │──▶│ Execute  │──▶│ Report   │  │  │
│   │   │  Task    │   │  (LLM)   │   │ (Skills) │   │  Result  │  │  │
│   │   └──────────┘   └──────────┘   └──────────┘   └──────────┘  │  │
│   │        │              │              │              │          │  │
│   │        ▼              ▼              ▼              ▼          │  │
│   │   [JSON]        [Tool Plan]    [API Calls]    [JSON Result]  │  │
│   │                                                                   │  │
│   └────────────────────────────────────────────────────────────────┘  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🔷 Layer 3: Orchestration Layer (编排层)

The Master coordinates multiple Nodes.

```
Orchestration Layer - Master
┌────────────────────────────────────────────────────────────────────────┐
│                              Master Agent                               │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐  │
│   │  1️⃣  Task Distributor (任务分发)                                 │  │
│   │      ┌─────────────────────────────────────────────────────┐    │  │
│   │      │  Input: Task with requirements                       │    │  │
│   │      │  Process:                                           │    │  │
│   │      │    1. Parse task requirements                       │    │  │
│   │      │    2. Match with node capabilities                  │    │  │
│   │      │    3. Select optimal node(s)                       │    │  │
│   │      │    4. Dispatch to queue                              │    │  │
│   │      │  Output: Task in node's queue                       │    │  │
│   │      └─────────────────────────────────────────────────────┘    │  │
│   └────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│   ┌────────────────────────────────────────────────────────────────┐  │
│   │  2️⃣  Result Aggregator (结果聚合)                                │  │
│   │      ┌─────────────────────────────────────────────────────┐    │  │
│   │      │  Input: Results from multiple nodes                 │    │  │
│   │      │  Process:                                           │    │  │
│   │      │    1. Collect partial results                       │    │  │
│   │      │    2. Merge/resolve conflicts                       │    │  │
│   │      │    3. Generate final output                        │    │  │
│   │      │  Output: Aggregated result                          │    │  │
│   │      └─────────────────────────────────────────────────────┘    │  │
│   └────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│   ┌────────────────────────────────────────────────────────────────┐  │
│   │  3️⃣  Health Monitor (健康监测)                                  │  │
│   │      ┌─────────────────────────────────────────────────────┐    │  │
│   │      │  Metrics:                                           │    │  │
│   │      │    • Node online/offline status                    │    │  │
│   │      │    • Task success/failure rate                      │    │  │
│   │      │    • Response latency                               │    │  │
│   │      │    • Resource utilization                           │    │  │
│   │      └─────────────────────────────────────────────────────┘    │  │
│   └────────────────────────────────────────────────────────────────┘  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🔗 How Skills, MCP, and Agents Work Together

### Scenario: "Research latest AI news and create a report"

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              MASTER                                      │
│  Task: "Research latest AI news and create a report"                   │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
         ▼                         ▼                         ▼
   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
   │  Node Alpha  │         │  Node Beta   │         │  Node Gamma  │
   │  (search)   │         │  (write)     │         │  (analyze)  │
   └──────┬───────┘         └──────┬───────┘         └──────┬───────┘
          │                        │                        │
          ▼                        ▼                        ▼
   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
   │ web_search  │         │    docx      │         │   analyze    │
   │  (Skill)    │         │   (Skill)   │         │   (Skill)   │
   └──────────────┘         └──────────────┘         └──────────────┘
          │                                                    
          ▼                                                    
   ┌──────────────�                                          
   │  MCP Server │                                          
   │ (News API)  │                                          
   └──────────────┘                                          
          │                        │                         │
          └────────────────────────┼─────────────────────────┘
                                   ▼
                          ┌──────────────┐
                          │  AGGREGATOR │
                          │  - Merge    │
                          │  - Format   │
                          │  - Output   │
                          └──────────────┘
```

---

## 🔄 Skill Chaining (技能链)

Skills can be chained in sequence or parallel:

### Sequential Chain (顺序链)

```
Task: "Find restaurant, get info, save to Notion"

┌─────────┐    ┌─────────┐    ┌─────────┐
│ web_    │───▶│  docx   │───▶│  MCP    │
│ search  │    │ (parse) │    │ notion  │
└─────────┘    └─────────┘    └─────────┘
   │              │              │
   ▼              ▼              ▼
 [query]    [structured]   [saved to
                      database]
```

### Parallel Fork (并行分叉)

```
Task: "Search 5 different topics in parallel"

                    ┌─── web_search (topic1)
                    ├─── web_search (topic2)
┌─────────┐  ──────▶├─── web_search (topic3) ──▶ AGGREGATOR ──▶ Report
│  Task   │         ├─── web_search (topic4)
└─────────┘         └─── web_search (topic5)
```

---

## 🎯 Capability Matching

The Master matches tasks to nodes based on capabilities:

```python
class CapabilityMatcher:
    """Match task requirements to node capabilities."""
    
    def match(self, task, nodes):
        # 1. Extract required capabilities from task
        required = task.get_requirements()  # ["search", "write", "notion"]
        
        # 2. Find nodes with ALL required capabilities
        candidates = []
        for node in nodes:
            node_caps = node.get_capabilities()  # ["search", "write", "code"]
            
            if all(cap in node_caps for cap in required):
                candidates.append(node)
        
        # 3. Score by preference
        scored = self.score_by_preference(task, candidates)
        
        # 4. Return best match
        return max(scored, key=lambda n: n.score)
```

---

## 📊 Module Interaction Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           USER / API                                    │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              MASTER                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │  Task Queue  │    │  Scheduler   │    │  Aggregator │              │
│  │  (files)    │───▶│  (match)    │───▶│  (merge)    │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│         │                   │                   │                       │
└─────────┼───────────────────┼───────────────────┼───────────────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                             NODES                                        │
│                                                                         │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐            │
│   │   Alpha      │    │    Beta      │    │   Gamma      │   ...      │
│   │  ┌────────┐  │    │  ┌────────┐  │    │  ┌────────┐  │            │
│   │  │Agent  │  │    │  │Agent  │  │    │  │Agent  │  │            │
│   │  │(LLM)  │  │    │  │(LLM)  │  │    │  │(LLM)  │  │            │
│   │  └──┬────┘  │    │  └──┬────┘  │    │  └──┬────┘  │            │
│   │     │        │    │     │        │    │     │        │            │
│   │     ▼        │    │     ▼        │    │     ▼        │            │
│   │  ┌────────┐  │    │  ┌────────┐  │    │  ┌────────┐  │            │
│   │  │ Skill  │  │    │  │ Skill  │  │    │  │ Skill  │  │            │
│   │  │ Runner │  │    │  │ Runner │  │    │  │ Runner │  │            │
│   │  └──┬────┘  │    │  └──┬────┘  │    │  └──┬────┘  │            │
│   └─────┼───────┘    └─────┼───────┘    └─────┼───────┘            │
│         │                   │                   │                       │
└─────────┼───────────────────┼───────────────────┼───────────────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          CAPABILITIES                                    │
│                                                                         │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐            │
│   │  Skills  │   │    MCP   │   │  Tools   │   │  Models  │            │
│   │(OpenClaw)│   │ Servers  │   │(exec/etc)│   │ (LLMs)  │            │
│   └──────────┘   └──────────┘   └──────────┘   └──────────┘            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📝 Related Documents

| Document | Description |
|----------|-------------|
| [DEVICE_TYPES.md](DEVICE_TYPES.md) | Device categories (desktop/mobile/edge/cloud) |
| [SANDBOX.md](SANDBOX.md) | Isolation & security |
| [NODE-CONFIG.md](NODE-CONFIG.md) | Node configuration |
| [TASK-FORMAT.md](TASK-FORMAT.md) | Task specification |

---

## 🌐 Hub-Spoke Networking (v0.9+)

Cross-machine communication without tunnels, SSH, or public IPs.

```
Hub (port 18080) ←──── HTTP Poll ──── Agent (VM/remote)
```

Key components: `networking.py` (HubServer + HubAgent + HubClient), embedded in `master_api.py`.

See [MODULES.md](../MODULES.md#networkingpy--跨公网-hub-spoke-通信模块) for full API reference.

---

## 🔌 Agent Adapter Architecture (v0.11+)

Pluggable adapter layer for heterogeneous agent types:

```
HubAgent.execute_task()
    │
    ├── adapter_type=None → native echo
    ├── adapter_type="hermes" → HermesAdapter (ACP JSON-RPC 2.0)
    ├── adapter_type="evolver" → EvolverAdapter (sessions_send/file)
    └── adapter_type="openclaw" → OpenClawAdapter (HTTP Hub)
```

See [MODULES.md](../MODULES.md#agent_adapterpy--异构-agent-适配器基类) for adapter interface and implementation details.
