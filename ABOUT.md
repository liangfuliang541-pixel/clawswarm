# About ClawSwarm

> 🦞 *One lobster, commands the swarm*

[English](ABOUT.md) | [中文版](ABOUT_CN.md)

---

## Vision

**ClawSwarm = The Lobster Commander**

One lobster = one complete AI Agent (Brain + Memory + Tools).
ClawSwarm empowers a single lobster to **command an entire swarm** — like a head of state directing a nation, dispatching, coordinating, and unleashing the full potential of every agent.

This is not 1-to-1 orchestration. This is a command center:

- **Command** — capability-aware scheduling, priority queues, health scoring, circuit breakers
- **Direct** — DAG orchestration, parallel execution, result aggregation, global oversight
- **Scale** — 1 machine or 100, file queues or REST API, local or cloud
- **Unleash** — every lobster is a full Agent: researcher, coder, writer, all collaborating freely

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

## 2026 多 Agent 四条路线

2026年，multi-agent 没有收敛成统一标准，反而分叉成了四条产品路线：

| 路线 | 代表产品 | 核心问题 | ClawSwarm 对应 |
|---|---|---|---|
| **委派** | OpenAI Agents SDK | 解"任务委派" | 任务队列 + 节点分发 |
| **隔离** | Claude Code | 解"上下文隔离" | 每个 Agent 独立 workspace |
| **协作** | CodeBuddy | 解"团队协作" | HITL 审批 + 结果聚合 |
| **编排** | OpenClaw | 解"运行时编排" | **ClawSwarm = 编排的编排** |

第四条路线的独特价值：**龙虾可以指挥龙虾**。

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

## 与竞品的差异化

| 维度 | ClawSwarm | crewAI | AutoGen | Anthropic Managed |
|------|-----------|--------|---------|-------------------|
| 跨设备协同 | ✅ SMB/共享文件夹 | ❌ | ❌ | ❌ 云端托管 |
| 文件队列 | ✅ 无数据库依赖 | ❌ | ❌ | ❌ |
| 运行时隔离 | ✅ 每个龙虾独立 workspace | ❌ | ❌ | ✅ 沙箱 |
| HITL 审批 | ✅ Checkpoint | ❌ | ❌ | ❌ |
| 分布式 | ✅ 即插即用节点 | ❌ | ❌ | ❌ |
| 编排层级 | **编排其他编排** | 单层 | 单层 | 单层 |

---

## 技术栈

- **语言**：Python 3.8+
- **LLM**：OpenAI / Anthropic / Gemini（可混用）
- **协议**：MCP（工具扩展）+ A2A（龙虾间通信）
- **存储**：文件系统（JSON 队列，无数据库）
- **传输**：SMB / 网络共享文件夹 / 云存储
- **观测**：OpenTelemetry（可选）
- **部署**：Docker（单命令启动）

---

## 竞品对比（2026年4月）

### Anthropic Managed Agents
- 官方托管云平台
- Brain/Hands/Session 三层架构
- 沙箱隔离 + 凭证隔离
- **ClawSwarm 的机会**：去中心化替代，本地运行，不上云

### OpenAI Agents SDK  
- delegation patterns（Handoffs）
- Manager → Expert Agent 委派模式
- **ClawSwarm 的机会**：更灵活的调度 + 跨设备

### LangGraph / AutoGen / CrewAI
- 单机 Python 框架
- **ClawSwarm 的机会**：跨机器 + 文件队列 + 无数据库

---

## 发展路线

| 版本 | 里程碑 | 状态 |
|------|---------|------|
| v0.7 | ClawSwarm Skill + sessions_spawn 集成 | ✅ 已完成 |
| v0.8 | MCP Server + Dashboard + ClawChat | ✅ 已完成 |
| v0.9 | Hub-Spoke 跨公网通信 | ✅ 已完成 |
| v0.10 | Hub 嵌入 master_api + Bug 修复 | ✅ 已完成 |
| v0.11 | 异构 Agent 适配器（Hermes/Evolver/OpenClaw）| ✅ 已完成 |
| v0.12 | 企业级基础设施（认证/指标/队列/租户）| ✅ 已完成 |
| v0.13 | IoT/边缘计算 + 联邦学习 + 自动扩缩容 | ✅ 已完成 |
| v0.14 | 生产就绪 — 共享文件夹即插即用 | 📋 规划中 |

---

## 为什么叫 ClawSwarm

- **龙虾** = 一个完整的 Agent（Brain + Hands + Session）
- **群** = 多龙虾协同，分工明确
- **🦞** = 有个性、有能力、有记忆、独立行动

就像真正的龙虾群：每只都有自己的领地，但可以协作捕猎。

---

## 引用

如果 ClawSwarm 对你的研究有帮助，请引用：

```bibtex
@software{clawswarm2026,
  title = {ClawSwarm: OpenClaw-Native Multi-Agent Orchestration Platform},
  author = {liangfuliang541-pixel},
  year = {2026},
  url = {https://github.com/liangfuliang541-pixel/clawswarm},
  version = {0.13.0}
}
```
