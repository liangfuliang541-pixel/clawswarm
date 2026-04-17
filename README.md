# 🦞 ClawSwarm - Multi-Agent Orchestration Platform

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.11.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.8+-green" alt="Python">
  <img src="https://img.shields.io/badge/tests-164%20passed-success" alt="Tests">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License">
  <img src="https://img.shields.io/badge/LOC-21.4k-blueviolet" alt="LOC">
</p>

<div align="center">

**[English](README.md)** | **[中文](README_CN.md)** | **[About](ABOUT.md)**

*One lobster, commands the swarm — unleash every agent's full potential*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-green.svg)](https://www.python.org/)
[![GitHub stars](https://img.shields.io/github/stars/liangfuliang541-pixel/clawswarm?style=social)](https://github.com/liangfuliang541-pixel/clawswarm/stargazers)

*Built with ❤️ by [liangfuliang541-pixel](https://github.com/liangfuliang541-pixel)*

</div>

---

## ⭐ Why ClawSwarm?

| Feature | ClawSwarm | crewAI | AutoGen |
|---------|-----------|--------|---------|
| **Zero-config Setup** | ✅ JSON only | ❌ Python code | ❌ Python code |
| **File-based Queue** | ✅ No DB needed | ❌ External services | ❌ External services |
| **OpenClaw Native** | ✅ Deep integration | ❌ | ❌ |
| **Cross-machine** | ✅ Hub-Spoke + SMB | ❌ | ❌ |
| **Heterogeneous Agents** | ✅ Hermes/Evolver/OpenClaw | ❌ | ❌ |
| **Offline Resilient** | ✅ Local queue | ❌ | ❌ |
| **Voice Control** | ✅ Via OpenClaw | ❌ | ❌ |

> **TL;DR**: ClawSwarm is the easiest way to coordinate multiple AI Agents across machines with zero infrastructure.

---

## ✨ Features

- 🦞 **Multi-Agent Orchestration** — Spawn and coordinate multiple AI agents in parallel
- 🧠 **Capability-Aware Scheduling** — Tasks routed to agents based on their capabilities
- 🔀 **DAG Workflows** — Build dependency graphs, execute in parallel where possible
- 🌐 **Hub-Spoke Networking** — Cross-machine communication without tunnels or public IPs
- 🔌 **Heterogeneous Agent Adapters** — Connect Hermes (ACP), Evolver, and OpenClaw agents
- 🤖 **MCP Server** — Expose ClawSwarm as MCP tools for other agents to call
- 💬 **ClawChat** — Agent-to-agent real-time messaging with SQLite persistence and WebSocket streaming
- 🖥️ **Web Dashboard** — Real-time monitoring with WebSocket event streaming + built-in chat panel
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

### Start Hub + Agent Node

```bash
# Start Hub (embedded in master_api.py)
python master_api.py --port 50010 --hub-port 18080

# Start a local agent node
python networking.py agent --hub-url http://localhost:18080 --agent-id local-01

# Start a Hermes agent node (with ACP adapter)
python networking.py agent --hub-url http://localhost:18080 --agent-id hermes-01 \
  --adapter-type hermes \
  --adapter-config '{"hermes_bin":"hermes","model":"qwen2.5:72b"}'

# Submit a task via HubClient
python networking.py client --hub-url http://localhost:18080 \
  --task "Fetch https://httpbin.org/json" --task-type fetch
```

### Or Use the Classic File Queue

```bash
# Option 1: Use deploy script
./deploy.sh install-deps
./deploy.sh local

# Option 2: Docker Compose
cp .env.template .env && docker compose up -d

# Option 3: Manual CLI
python cli.py start-cluster
python cli.py add-task "Research latest AI trends"
python cli.py status
```

---

## 🏗️ Architecture

### Hub-Spoke Model (Cross-Machine)

```
┌──────────────────────────────────────────────┐
│              Hub (port 18080)                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Agent    │ │ Task     │ │ Result       │ │
│  │ Registry │ │ Queue    │ │ Store        │ │
│  └────┬─────┘ └────▲─────┘ └──────┬───────┘ │
└───────┼─────────────┼──────────────┼─────────┘
        │             │              │
        │    HTTP Poll + Submit      │
        │             │              │
┌───────┴─────┐ ┌────┴─────┐ ┌──────┴───────┐
│ OpenClaw    │ │ Hermes   │ │ Evolver      │
│ Agent       │ │ (ACP)    │ │ (Skill)      │
│ (native)    │ │ Adapter  │ │ Adapter      │
└─────────────┘ └──────────┘ └──────────────┘
```

### Local File Queue Model

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

## 🔌 Agent Adapters

ClawSwarm supports heterogeneous agent types through a pluggable adapter layer:

| Adapter | Protocol | Use Case |
|---------|----------|----------|
| `openclaw` | HTTP Hub polling | Native OpenClaw agents |
| `hermes` | ACP (stdin/stdout JSON-RPC 2.0) | Nous Research Hermes agents |
| `evolver` | sessions_send / file polling | OpenClaw Evolver skill agents |

```python
from agent_adapter import get_adapter

# Create a Hermes adapter
adapter = get_adapter("hermes", "hermes-01", {
    "hermes_bin": "hermes",
    "model": "qwen2.5:72b",
    "capabilities": ["code", "reason"]
})
adapter.start()
result = await adapter.execute({"prompt": "Write a fibonacci function"})
```

---

## 🖥️ Dashboard

Web UI monitoring panel with real-time cluster status, task DAG, and execution results.

```bash
python dashboard/dashboard.py --port 5000
# Open http://localhost:5000
```

**Features**: Node status panel, task DAG visualization, real-time WebSocket events, built-in chat panel, natural language task submission.

---

## 🤖 MCP Server

Expose ClawSwarm as MCP tools for other agents to call.

```bash
python mcp_server.py
# Or via mcporter: mcporter call clawswarm.clawswarm_status
```

**MCP Tools**: `clawswarm_spawn`, `clawswarm_poll`, `clawswarm_submit`, `clawswarm_status`, `clawswarm_nodes`, `clawswarm_aggregate`, `clawswarm_dead_letter`, `clawswarm_health`

---

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

## 🤝 Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

## 📄 License

**MIT** - See [LICENSE](LICENSE)

---

<div align="center">

**⭐ Star us on GitHub!** | **让 AI Agent 像龙虾群一样协同工作** 🦞

</div>
