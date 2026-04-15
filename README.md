# 🦞 ClawSwarm - Multi-Agent Orchestration Framework

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.9.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.8+-green" alt="Python">
  <img src="https://img.shields.io/badge/tests-107%20passed-success" alt="Tests">
  <img src="https://img.shields.io/badge/license-AGPL%20v3-orange" alt="License">
  <img src="https://img.shields.io/badge/MCP-2024--11--05-purple" alt="MCP">
</p>

<div align="center">

**[English](README.md)** | **[中文](README_CN.md)** | **[About](ABOUT.md)**

*One lobster, commands the swarm — unleash every agent's full potential*

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-green.svg)](https://www.python.org/)
[![GitHub stars](https://img.shields.io/github/stars/liangfuliang541-pixel/clawswarm?style=social)](https://github.com/liangfuliang541-pixel/clawswarm/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/liangfuliang541-pixel/clawswarm?style=social)](https://github.com/liangfuliang541-pixel/clawswarm/network)
[![GitHub issues](https://img.shields.io/github/issues/liangfuliang541-pixel/clawswarm)](https://github.com/liangfuliang541-pixel/clawswarm/issues)
[![Discord](https://img.shields.io/discord/123456789?label=Discord)](https://discord.gg/clawswarm)

*Built with ❤️ by [liangfuliang541-pixel](https://github.com/liangfuliang541-pixel)*

</div>

---

## ⭐ Why ClawSwarm?

| Feature | ClawSwarm | crewAI | AutoGen |
|---------|-----------|--------|---------|
| **Zero-config Setup** | ✅ JSON only | ❌ Python code | ❌ Python code |
| **File-based Queue** | ✅ No DB needed | ❌ External services | ❌ External services |
| **OpenClaw Native** | ✅ Deep integration | ❌ | ❌ |
| **Cross-machine** | ✅ SMB/Shared folder | ❌ | ❌ |
| **Offline Resilient** | ✅ Local queue | ❌ | ❌ |
| **Voice Control** | ✅ Via OpenClaw | ❌ | ❌ |

> **TL;DR**: ClawSwarm is the easiest way to coordinate multiple AI Agents across machines with zero infrastructure.

---

## ✨ Features

- 🦞 **Multi-Agent Orchestration** — Spawn and coordinate multiple AI agents in parallel
- 🧠 **Capability-Aware Scheduling** — Tasks routed to agents based on their capabilities
- 🔀 **DAG Workflows** — Build dependency graphs, execute in parallel where possible
- 🤖 **MCP Server** — Expose ClawSwarm as MCP tools for other agents to call
- 🖥️ **Web Dashboard** — Real-time monitoring with WebSocket event streaming
- 📊 **OpenTelemetry** — Production-grade observability out of the box
- 🔒 **Sandbox Security** — Path whitelisting, command blacklisting, audit logging
- ✅ **HITL Checkpoint** — Human-in-the-loop approval for critical tasks
- 🐳 **Docker Ready** — Full Docker + Docker Compose deployment support
- 🔄 **Zero Dependencies** — File-based queue in Phase 1, no message broker needed

---

## 🚀 Quick Start

### Install

```bash
git clone https://github.com/liangfuliang541-pixel/clawswarm.git
cd clawswarm
pip install -r requirements.txt
```

### Start Master + 2 Nodes

```bash
# Option 1: Use deploy script (recommended)
./deploy.sh install-deps
./deploy.sh local

# Option 2: Docker Compose (recommended for deployment)
cp .env.template .env   # edit .env with your API keys
docker compose up -d

# Option 3: Manual CLI
python cli.py start-cluster           # start 3-node demo cluster
python cli.py add-task "调研2026年AI最新进展"  # add a task
python cli.py status                  # check status
```

### Add Tasks

```bash
# Add a task via CLI
python cli.py add-task "Research latest AI trends" --type research --priority 5

# Add via REST API (master running)
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"text":"Research latest AI trends","type":"research","priority":5}'
```

### Check Status

```bash
python cli.py status
# or via REST API
curl http://localhost:5000/tasks
```

### Docker Deployment

```bash
cp .env.template .env
docker compose up -d
# Master API:  http://localhost:5000
# Event WS:    ws://localhost:8765
# Node Alpha:  http://localhost:5171
# Node Beta:   http://localhost:5172
```

------

## 💠 One-Command Orchestration

```bash
# Decompose task into sub-tasks, enqueue, and print spawn commands for AI
python orchestrate.py "Search AI news and write a comparison report"

# Interactive demo with 4 preset scenarios
python demo.py

# Run a specific preset scenario
python demo.py --scenario ai-news

# Custom task
python demo.py --custom "Analyze MCP protocol and suggest implementation"
```

> Set `OPENAI_API_KEY` for LLM-powered task decomposition (GPT-4o-mini). Without it, a rule engine is used.



## 📖 Documentation

| Doc | Description |
|-----|-------------|
| [📚 Architecture](docs/ARCHITECTURE.md) | Technical architecture & design |
| [🗺️ Roadmap](docs/EVOLUTION.md) | Evolution from MVP to product |
| [📝 Task Format](docs/TASK-FORMAT.md) | Task JSON specification |
| [⚙️ Node Config](docs/NODE-CONFIG.md) | Node configuration guide |
| [🔌 API Reference](docs/API.md) | CLI & Python API |
| [🚀 Deployment](docs/DEPLOY.md) | Docker & local deployment guide |
| [📖 Modules](MODULES.md) | Codebase module index |
| [🧠 OpenClaw Skill](skill/) | One-command install into OpenClaw |
| [🦞 About](ABOUT.md) | Project story, philosophy & roadmap |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│              Master Agent                    │
│  ┌─────────┐ ┌─────────┐ ┌─────────────┐   │
│  │ Task    │ │ Result  │ │ Health      │   │
│  │ Dispatch│ │ Aggregat│ │ Monitor     │   │
│  └────┬────┘ └────▲────┘ └──────┬──────┘   │
└───────┼───────────┼──────────────┼──────────┘
        │           │              │
        ▼           │              ▼
   ┌─────────────────────────────────────┐
   │      Shared Storage (queue/)       │
   └─────────────────────────────────────┘
        ▲           ▲              ▲
        │           │              │
┌───────┴───┐ ┌────┴────┐ ┌──────┴──────┐
│  Node 1   │ │ Node 2  │ │   Node N    │
│(search)   │ │(write)  │ │  (code)     │
└───────────┘ └─────────┘ └─────────────┘
```

---

## 🖥️ Dashboard

Web UI 监控面板，实时展示龙虾集群状态、任务 DAG、执行结果。

```bash
# 启动（自动连接 MonitorService）
python dashboard/dashboard.py --port 5000

# 打开浏览器
# http://localhost:5000
```

**功能**：
- 🐠 节点状态面板（在线/离线/心跳）
- 📊 统计面板（节点数/在线数/待执行/已完成）
- ➕ 自然语言提交任务（直接触发执行）
- 🔀 任务 DAG 可视化（pending → running → success/failed）
- 📡 实时事件流（WebSocket 推送）
- 💬 任务列表 + 实时状态更新

**API**：
- `GET /api/status` — 集群整体状态
- `GET /api/nodes` — 节点列表
- `GET /api/tasks` — 任务历史
- `POST /api/tasks` — 提交新任务
- `WS /ws` — 实时 WebSocket 事件流

---

## 🤖 MCP Server

让其他 Agent 通过 MCP (Model Context Protocol) 调用 ClawSwarm。

```bash
# 直接运行 MCP 服务器（stdio 模式）
python mcp_server.py

# 通过 mcporter 调用
mcporter call --stdio -- python mcp_server.py clawswarm_spawn '{"prompt":"Hello"}'
```

**MCP Tools**：

| Tool | 作用 |
|------|------|
| `clawswarm_spawn` | 启动子龙虾执行任务 |
| `clawswarm_poll` | 轮询等待结果文件 |
| `clawswarm_submit` | 提交任务到队列 |
| `clawswarm_status` | 获取集群整体状态 |
| `clawswarm_nodes` | 列出所有节点 |
| `clawswarm_aggregate` | 聚合多个结果文件 |

**在 OpenClaw Skill 中使用**：
```bash
# 方式 1：通过已注册的 mcporter server 直接调用
mcporter call clawswarm.clawswarm_spawn prompt="Search latest AI news" label="news"

# 方式 2：通过 --stdio 临时调用
mcporter call --stdio -- python mcp_server.py clawswarm_spawn '{"prompt":"Hello"}'
```

**注册到 mcporter**（一次性）：
```json
// ~/.mcporter/mcporter.json
{
  "mcpServers": {
    "clawswarm": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/path/to/clawswarm"
    }
  }
}
```

---

## 📚 Examples

```bash
python examples/01_quickstart.py   # 快速上手：提交 + 轮询
python examples/02_parallel.py      # 并行任务：多任务 + 聚合
python examples/04_mcp_demo.py     # MCP 协议调用示例
```

---

## 🤝 Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

- 🐛 Report bugs
- 💡 Request features
- 📝 Submit PRs
- 🌐 Translate docs

---

## 📄 License

**AGPL v3** - See [LICENSE](LICENSE)

Commercial license available. Contact: liangfuliang541@gmail.com

---

## 🌍 Community

- 📖 [Documentation](docs/)
- 🐛 [Issues](https://github.com/liangfuliang541-pixel/clawswarm/issues)
- 💬 [Discussions](https://github.com/liangfuliang541-pixel/clawswarm/discussions)

---

<div align="center">

**⭐ Star us on GitHub!** | **让 AI Agent 像龙虾群一样协同工作** 🦞

</div>
