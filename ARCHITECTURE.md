# ClawSwarm 架构设计文档

**版本：** v0.11  
**日期：** 2026-04-18  
**详细架构：** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | [docs/ARCHITECTURE_CN.md](docs/ARCHITECTURE_CN.md)

---

## 当前架构概览（v0.11）

ClawSwarm 支持两种运行模式：**本地文件队列** 和 **Hub-Spoke 跨公网**。

### 本地文件队列模式

```
Master (scheduler + orchestrator)
    │
    ├── queue/ ────→ Node Alpha (fetch/exec/python)
    │                Node Beta  (search/write)
    │                Node Gamma (analyze/report)
    │
    └── results/ ←── 节点完成写入
```

### Hub-Spoke 跨公网模式

```
┌──────────────────────────────────────────────┐
│              Hub (port 18080)                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Agent    │ │ Task     │ │ Result       │ │
│  │ Registry │ │ Queue    │ │ Store        │ │
│  └────┬─────┘ └────▲─────┘ └──────┬───────┘ │
└───────┼─────────────┼──────────────┼─────────┘
        │    HTTP 轮询 + 提交结果     │
┌───────┴─────┐ ┌────┴─────┐ ┌──────┴───────┐
│ OpenClaw    │ │ Hermes   │ │ Evolver      │
│ (native)    │ │ (ACP)    │ │ (Skill)      │
└─────────────┘ └──────────┘ └──────────────┘
```

### 适配器架构

```
HubAgent.execute_task()
    │
    ├── adapter_type=None → 原生 echo 执行
    ├── adapter_type="hermes" → HermesAdapter (ACP JSON-RPC)
    ├── adapter_type="evolver" → EvolverAdapter (sessions_send/file)
    └── adapter_type="openclaw" → OpenClawAdapter (HTTP Hub)
```

---

## 核心设计原则

| 原则 | 说明 |
|------|------|
| **零基础设施** | 文件队列无数据库依赖，Hub-Spoke 无需公网 IP |
| **能力感知** | 任务根据节点能力路由，异构 Agent 通过适配器统一接入 |
| **优雅降级** | OpenTelemetry/LLM/适配器 均可选，缺失时 fallback |
| **原子操作** | 文件 rename 保证并发安全，Hub 队列原子 pop |

---

## 历史架构文档

- v0.1 原始设计：见 git history (`91e0c5f` 之前)
- v0.6+ 模块化架构：见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
