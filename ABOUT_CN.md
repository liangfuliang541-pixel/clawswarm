# 关于 ClawSwarm

> 🦞 *一只龙虾指挥另一只龙虾*

[English](ABOUT.md) | [中文](ABOUT_CN.md)

---

## 一句话定位

**ClawSwarm = 龙虾指挥龙虾**

一只龙虾 = 一个完整的 AI Agent（Brain + Memory + Tools）
多只龙虾协同 = 跨设备、跨平台、跨机器的分布式 Agent 编排平台

---

## 核心洞察

### 为什么 ClawSwarm 押注在正确的地方

2026年4月，Anthropic 发布 Claude Managed Agents，技术博客反复强调一个词：**Agent Harness**。

核心观点：

> 每个 Agent 请求都应该在独立的沙箱环境里运行。

顺着这条思路深挖，Anthropic 把 Agent 运行时拆成三层：

| 层 | 职责 | ClawSwarm 对应 |
|---|---|---|
| **Brain** | 推理 + prompt 循环 + tool_call 决策 | Agent 的 LLM + 指令理解 |
| **Hands** | 沙箱 + 工具（Bash/文件/Web/MCP） | Agent 的执行能力 |
| **Session** | 事件日志 + SSE 流 + 断连恢复 | Agent 的记忆 + 状态 |

这正是 ClawSwarm 的核心抽象：

> **一只龙虾 = Brain + Hands + Session = 一个完整 Agent**

Anthropic 在卖"官方托管版"，ClawSwarm 在做"去中心化版"。

---

## ClawSwarm 架构

```
用户（自然语言任务）
    │
    ▼
Orchestrator（LLM 分解）
    │
    ├──→ Queue（文件队列，跨设备共享）
    │
    ▼
龙虾 Alpha（Brain + Hands + Session）
    │
    ├──→ Queue（子任务）
    │
    ▼
龙虾 Beta / Gamma / ...（并行执行）
    │
    ▼
结果聚合（aggregate）
    │
    ▼
最终输出
```

---

## 龙虾模型：每个 Agent 的三层结构

```
┌──────────────────────────────────┐
│  🧠 Brain（LLM）                │
│  - 指令理解 + 推理               │
│  - 子任务分解                    │
│  - 决策                          │
├──────────────────────────────────┤
│  🦷 Hands（执行层）              │
│  - Bash / 文件 / Web Fetch       │
│  - MCP servers（扩展工具）        │
│  - HITL 审批（人类介入）         │
├──────────────────────────────────┤
│  📦 Session（状态层）            │
│  - 记忆 + 上下文持久化           │
│  - 工作目录隔离                  │
│  - 凭证隔离                      │
└──────────────────────────────────┘
```

---

## 核心概念

### Agent 角色

Agent 具备专业化能力，作为轻量级进程运行：

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
