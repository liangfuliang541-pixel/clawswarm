# 关于 ClawSwarm

> 🦞 *一只龙虾，统帅千军万马*

[English](ABOUT.md) | [中文](ABOUT_CN.md)

---

## 一句话定位

**ClawSwarm = 龙虾统帅**

一只龙虾 = 一个完整的 AI Agent（Brain + Memory + Tools）
ClawSwarm 让一只龙虾能**统帅千军万马**——像国家领袖指挥整个国家一样，调度、协同、释放每一个 Agent 的全部潜力。

这不是一对一的指挥，而是一个指挥中枢：
- **统**：统一调度——能力感知、优先级队列、健康评分、自动熔断
- **帅**：帅旗所指——DAG 编排、并行执行、结果聚合、全局掌控
- **千军**：无限扩展——1 台或 100 台机器，文件队列或 REST API，本地或云端
- **万马**：百花齐放——每只龙虾都是完整 Agent，researcher/coder/writer 自由协作

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

### v0.7 — OpenClaw Agent 启动 ✅ 已完成
- `_execute_spawn` → real `sessions_spawn`
- 打包为 OpenClaw Skill
- `swarm run` from OpenClaw CLI

### v0.8 — Web UI + MCP Server ✅ 已完成
- FastAPI dashboard (`/dashboard`)
- MCP Server (8 tools)
- Real-time task status via WebSocket
- Node health panel

### v0.9 — 跨公网通信 ✅ 已完成
- Hub-Spoke 反向轮询架构
- networking.py（HubServer + HubAgent + HubClient）
- ClawChat Agent 间聊天

### v0.10 — Hub 嵌入 + 稳定性修复 ✅ 已完成
- Hub 嵌入 master_api.py
- ThreadingTCPServer 修复
- 4 个关键 Bug 修复

### v0.11 — 异构 Agent 适配器 ✅ 已完成
- agent_adapter.py 抽象基类 + 注册表
- hermes_adapter.py (ACP 协议)
- evolver_adapter.py (sessions_send/文件轮询)
- openclaw_adapter.py (HTTP Hub 轮询)
- HubAgent + adapter 集成
- 164 测试全绿

### v0.12 — 企业级基础设施（认证/指标/队列/租户）✅ 已完成
- 任务队列（优先级/重试/死信队列）
- 认证授权（API Key/JWT/RBAC）
- Prometheus 指标收集
- 多租户命名空间隔离
- VM 安全组开端口
- Hermes binary 安装 + 真实 e2e
- Evolver 适配器真实调用

### v0.13 — IoT/边缘计算 + 联邦学习 + 自动扩缩容 ✅ 已完成
- 边缘设备适配器（HTTP/MQTT/WebSocket/CoAP）
- FedAvg/FedProx 联邦聚合
- 负载感知弹性伸缩

### v0.14 — 生产就绪 📋 规划中
- DAG 可视化
- Prometheus 指标端点
- SMB 共享目录部署 guide
- GitHub Actions 持续集成

### 未来规划
- [ ] LangChain / LlamaIndex 集成
- [ ] 云原生模式（Redis + PostgreSQL）
- [ ] Web 版 DAG 编辑器
- [ ] 商业授权（MIT + 企业版）

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
- **License**: [MIT](LICENSE)
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
