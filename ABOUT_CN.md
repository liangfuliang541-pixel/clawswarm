# 关于 ClawSwarm

> 🦞 *像龙虾群一样协调多个 AI Agent*

[English](ABOUT.md) | [中文](ABOUT_CN.md)

---

## What Is ClawSwarm?

ClawSwarm is an **OpenClaw-native multi-agent orchestration platform** that lets you describe a complex task in plain language and have it automatically decomposed, distributed, executed, and aggregated by a swarm of specialized AI agents.

你这样写：

```
"帮我调研 AI Agent 领域的最新进展，搜索技术趋势，分析主流产品，最后生成一份报告"
```

ClawSwarm 自动这样执行：

```
task_001 [fetch]   → claw_alpha (search+analyze)
task_002 [fetch]   → claw_beta  (search+write)
                      ↓ (both done)
task_003 [report]  → claw_gamma (report)
                      ↓
              📋 Final Aggregated Report
```

****无需 Python 代码。** JSON 文件或自然语言——就's it.

---

## 缘起

现有多 Agent 框架与实际生产环境存在根本性的不匹配： have a fundamental mismatch with how AI agents actually work in production:

| Problem | crewAI / AutoGen | ClawSwarm |
|---------|-----------------|-----------|
| Deploy on a new machine | Rewrite Python, install deps | Copy one folder |
| Run without internet | External services required | ✅ File queue, offline OK |
| Coordinate across 3 computers | ❌ | ✅ Shared folder, zero config |
| Monitor real-time progress | Web UI only | WebSocket + CLI + Web UI |
| Human approval on critical steps | ❌ | ✅ Built-in HITL |
| See what every agent is doing | ❌ | ✅ OpenTelemetry tracing |
| Docker one-command deploy | ❌ | ✅ `docker compose up` |

ClawSwarm 从设计之初就坚持： **zero-infrastructure**, **cross-machine**, and **deeply integrated with OpenClaw**.

---

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    你的对话                     │
│              "帮我调研 X 并写报告"                        │
└──────────────────────┬──────────────────────────────────┘
                       │ cli.py / Web UI / API
                       ▼
┌──────────────────────────────────────────────────────────┐
│              ClawSwarm 编排器                       │
│                                                          │
│  ┌──────────────┐  ┌─────────────┐  ┌───────────────┐  │
│  │  Task        │  │  DAG        │  │  Result       │  │
│  │  Decomposer  │→ │  Scheduler  │→ │  Aggregator   │  │
│  │  (LLM/rule) │  │  (capability)│  │  (LLM/template)│ │
│  └──────────────┘  └─────────────┘  └───────────────┘  │
│                                                          │
│  ┌──────────────┐  ┌─────────────┐  ┌───────────────┐  │
│  │ HITL         │  │ Observ-     │  │ Events        │  │
│  │ Checkpoints  │  │ ability     │  │ (WebSocket)   │  │
│  └──────────────┘  └─────────────┘  └───────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │ File Queue / REST API
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
┌─────────────────┐ ┌──────────┐ ┌──────────────┐
│  claw_alpha     │ │ claw_beta│ │ claw_gamma   │
│  search+write   │ │ read+    │ │ search+      │
│  +code          │ │ write    │ │ analyze+     │
│                 │ │          │ │ report       │
│  executor.py    │ │ executor │ │ executor     │
│  sessions_      │ │ .py      │ │ .py          │
│  spawn          │ │          │ │              │
└─────────────────┘ └──────────┘ └──────────────┘
         │             │             │
         └─────────────┴─────────────┘
                       │ results/
                       ▼
              ┌─────────────────┐
              │ Final Report    │
              └─────────────────┘
```

---

## 核心概念

### Agent 角色

Agent 具备专业化能力，作为轻量级进程运行： and run as lightweight processes:

```
claw_alpha  →  researcher  (search + analyze)
claw_beta   →  writer      (write + read)
claw_gamma  →  analyst     (search + analyze + report)
```

### 任务生命周期

```
[Created] → [Queued] → [Assigned] → [In Progress] → [Done/Failed]
                                    ↓
                             [HITL Checkpoint] (optional pause)
```

### HITL（人工介入）

关键操作暂停等待人工审批：

```python
# When task priority >= 5, auto-pause
HITL_POLICY=by_priority --threshold 5

# Always approve (testing)
HITL_POLICY=always_approve

# Always require approval
HITL_POLICY=always_require
```

### DAG 执行

任务形成有向无环图：

```
    A ──┬── B
        ├── C
        └── D ── E
```

- A, B, C run **in parallel** (no dependencies)
- D 等待 A
- E 等待 D

---

## 技术栈

| Layer | Technology | Why |
|-------|-----------|-----|
| Orchestration | Python 3.8+ | Cross-platform, batteries included |
| LLM | OpenAI / Anthropic / Gemini / Ollama | Multi-provider abstraction |
| Agent Runtime | OpenClaw | Native agent execution |
| Tracing | OpenTelemetry | Vendor-neutral observability |
| Real-time | WebSocket + FastAPI | Live updates without polling |
| Deployment | Docker Compose | One-command production |
| Queue | File-based (JSON) | 零基础设施, offline OK |
| Security | Path whitelist + command blacklist | Sandboxed execution |

---

## 与竞品对比

| Feature | ClawSwarm | crewAI 0.88 | AutoGen 0.4 | LangGraph |
|---------|-----------|-------------|-------------|-----------|
| **Setup complexity** | Zero | Medium | Medium | High |
| **Multi-machine** | ✅ | ❌ | ❌ | ❌ |
| **Offline capable** | ✅ | ❌ | ❌ | ❌ |
| **HITL built-in** | ✅ | ❌ | ❌ | ❌ |
| **OpenTelemetry** | ✅ | ❌ | Partial | ❌ |
| **WebSocket events** | ✅ | ❌ | ❌ | ❌ |
| **Docker deploy** | ✅ | Manual | Manual | Manual |
| **No Python for tasks** | ✅ JSON | ❌ | ❌ | ❌ |
| **OpenClaw native** | ✅ | ❌ | ❌ | ❌ |

---

## 发展路线

### v0.7 — OpenClaw Agent 启动 (next)
- [ ] `_execute_spawn` → real `sessions_spawn`
- [ ] 打包为 OpenClaw Skill
- [ ] `swarm run` from OpenClaw CLI

### v0.8 — Web UI 监控面板
- [ ] FastAPI dashboard (`/dashboard`)
- [ ] Real-time task status via WebSocket
- [ ] One-click checkpoint approval
- [ ] Node health panel

### v1.0 — 生产就绪
- [ ] DAG 可视化
- [ ] Prometheus 指标端点
- [ ] SMB 共享目录部署 guide
- [ ] GitHub Actions 持续集成

### 未来规划
- [ ] LangChain / LlamaIndex 集成
- [ ] 云原生模式（Redis + PostgreSQL）
- [ ] Web 版 DAG 编辑器
- [ ] 商业授权（AGPL + 企业版）

---

## 设计理念

1. **零基础设施** — 如果需要数据库, a message queue, or a service mesh to run, it's not ClawSwarm.
2. **文件即 API** — 任务是 JSON，队列是文件夹，结果是文件. Unix 哲学遇上 AI Agent。
3. **优雅降级** — If OpenTelemetry isn't configured, logs still work. If LLM API key is missing, rule-based fallback kicks in.
4. **人类做主** — 关键操作始终暂停等待人工审批 for human approval. AI 辅助，人类决策。
5. **默认可观测** — 每个重要事件都被追踪、记录、发送, logged, and emitted. 调试运行中的集群应该很容易。

---

## 团队与社区

- **Author**: [liangfuliang541-pixel](https://github.com/liangfuliang541-pixel)
- **License**: [AGPL v3](LICENSE)
- **Issues**: [GitHub Issues](https://github.com/liangfuliang541-pixel/clawswarm/issues)
- **Discussions**: [GitHub Discussions](https://github.com/liangfuliang541-pixel/clawswarm/discussions)

---

## 引用

如果你在研究或项目中使用了 ClawSwarm, please cite:

```bibtex
@software{clawswarm,
  title = {ClawSwarm: OpenClaw-Native Multi-Agent Orchestration Framework},
  author = {liangfuliang541-pixel},
  url = {https://github.com/liangfuliang541-pixel/clawswarm},
  year = {2026},
}
```
