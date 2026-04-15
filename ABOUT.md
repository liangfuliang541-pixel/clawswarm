# About ClawSwarm

> 🦞 *Coordinate multiple AI Agents like a lobster swarm*

[English](ABOUT.md) | [中文](ABOUT_CN.md)

---

## What Is ClawSwarm?

ClawSwarm is an **OpenClaw-native multi-agent orchestration platform** that lets you describe a complex task in plain language and have it automatically decomposed, distributed, executed, and aggregated by a swarm of specialized AI agents.

You write this:

```
"帮我调研 AI Agent 领域的最新进展，搜索技术趋势，分析主流产品，最后生成一份报告"
```

ClawSwarm does this automatically:

```
task_001 [fetch]   → claw_alpha (search+analyze)
task_002 [fetch]   → claw_beta  (search+write)
                      ↓ (both done)
task_003 [report]  → claw_gamma (report)
                      ↓
              📋 Final Aggregated Report
```

**No Python code required.** JSON files or natural language — that's it.

---

## The Story

This project started because existing multi-agent frameworks have a fundamental mismatch with how AI agents actually work in production:

| Problem | crewAI / AutoGen | ClawSwarm |
|---------|-----------------|-----------|
| Deploy on a new machine | Rewrite Python, install deps | Copy one folder |
| Run without internet | External services required | ✅ File queue, offline OK |
| Coordinate across 3 computers | ❌ | ✅ Shared folder, zero config |
| Monitor real-time progress | Web UI only | WebSocket + CLI + Web UI |
| Human approval on critical steps | ❌ | ✅ Built-in HITL |
| See what every agent is doing | ❌ | ✅ OpenTelemetry tracing |
| Docker one-command deploy | ❌ | ✅ `docker compose up` |

ClawSwarm was built from the ground up to be **zero-infrastructure**, **cross-machine**, and **deeply integrated with OpenClaw**.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Your Conversation                     │
│              "帮我调研 X 并写报告"                        │
└──────────────────────┬──────────────────────────────────┘
                       │ cli.py / Web UI / API
                       ▼
┌──────────────────────────────────────────────────────────┐
│              ClawSwarm Orchestrator                       │
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

## Core Concepts

### Agent Roles

Agents have specialized capabilities and run as lightweight processes:

```
claw_alpha  →  researcher  (search + analyze)
claw_beta   →  writer      (write + read)
claw_gamma  →  analyst     (search + analyze + report)
```

### Task Lifecycle

```
[Created] → [Queued] → [Assigned] → [In Progress] → [Done/Failed]
                                    ↓
                             [HITL Checkpoint] (optional pause)
```

### HITL (Human-in-the-Loop)

Critical operations pause for human approval:

```python
# When task priority >= 5, auto-pause
HITL_POLICY=by_priority --threshold 5

# Always approve (testing)
HITL_POLICY=always_approve

# Always require approval
HITL_POLICY=always_require
```

### DAG Execution

Tasks form a directed acyclic graph:

```
    A ──┬── B
        ├── C
        └── D ── E
```

- A, B, C run **in parallel** (no dependencies)
- D waits for A
- E waits for D

---

## Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Orchestration | Python 3.8+ | Cross-platform, batteries included |
| LLM | OpenAI / Anthropic / Gemini / Ollama | Multi-provider abstraction |
| Agent Runtime | OpenClaw | Native agent execution |
| Tracing | OpenTelemetry | Vendor-neutral observability |
| Real-time | WebSocket + FastAPI | Live updates without polling |
| Deployment | Docker Compose | One-command production |
| Queue | File-based (JSON) | Zero infrastructure, offline OK |
| Security | Path whitelist + command blacklist | Sandboxed execution |

---

## Comparison with Alternatives

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

## Roadmap

### v0.7 — OpenClaw Agent Spawn (next)
- [ ] `_execute_spawn` → real `sessions_spawn`
- [ ] Package as OpenClaw Skill
- [ ] `swarm run` from OpenClaw CLI

### v0.8 — Web UI Dashboard
- [ ] FastAPI dashboard (`/dashboard`)
- [ ] Real-time task status via WebSocket
- [ ] One-click checkpoint approval
- [ ] Node health panel

### v1.0 — Production Ready
- [ ] DAG visualizer
- [ ] Prometheus metrics endpoint
- [ ] SMB shared folder deployment guide
- [ ] GitHub Actions CI/CD

### Future
- [ ] LangChain / LlamaIndex integration
- [ ] Cloud-native mode (Redis + PostgreSQL)
- [ ] Web-based DAG editor
- [ ] Commercial license (AGPL + enterprise)

---

## Philosophy

1. **Zero infrastructure** — If it needs a database, a message queue, or a service mesh to run, it's not ClawSwarm.
2. **File is the API** — Task is JSON, queue is a folder, result is a file. Unix philosophy meets AI agents.
3. **Fail gracefully** — If OpenTelemetry isn't configured, logs still work. If LLM API key is missing, rule-based fallback kicks in.
4. **Humans in charge** — Critical operations always pause for human approval. The AI assists; humans decide.
5. **Observable by default** — Every significant event is traced, logged, and emitted. Debugging a running swarm should be trivial.

---

## Team & Community

- **Author**: [liangfuliang541-pixel](https://github.com/liangfuliang541-pixel)
- **License**: [AGPL v3](LICENSE)
- **Issues**: [GitHub Issues](https://github.com/liangfuliang541-pixel/clawswarm/issues)
- **Discussions**: [GitHub Discussions](https://github.com/liangfuliang541-pixel/clawswarm/discussions)

---

## Citing

If you use ClawSwarm in your research or project, please cite:

```bibtex
@software{clawswarm,
  title = {ClawSwarm: OpenClaw-Native Multi-Agent Orchestration Framework},
  author = {liangfuliang541-pixel},
  url = {https://github.com/liangfuliang541-pixel/clawswarm},
  year = {2026},
}
```
