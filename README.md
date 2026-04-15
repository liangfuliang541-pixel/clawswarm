# 🦞 ClawSwarm - Multi-Agent Orchestration Framework

<div align="center">

**[English](README.md)** | **[中文](README_CN.md)** | **[About](ABOUT.md)**

*Coordinate multiple AI Agents like a lobster swarm*

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

| Feature | Description |
|---------|-------------|
| 🦞 **Multi-Node Coordination** | One Master coordinates multiple Node Agents |
| 🧠 **Smart Scheduling** | Auto-assign tasks based on node capabilities |
| 📊 **Result Aggregation** | Collect and merge results from all nodes |
| 💾 **Persistence** | File-based queue queue survives restarts |
| 🌐 **Cross-Machine** | Works across LAN via shared storage |
| 🔄 **Fault Tolerance** | Auto-retry failed tasks, stale task recovery |
| 🔌 **OpenClaw Native** | Seamless OpenClaw Agent integration via sessions_spawn |
| 🌍 **Bilingual** | Full English + Chinese documentation |
| ⏸️ **Human-in-the-Loop** | Checkpoint approval for critical tasks |
| 📡 **OpenTelemetry** | Distributed tracing + Prometheus metrics |
| 🔔 **WebSocket Events** | Real-time task/checkpoint event streams |
| 🚢 **Production Ready** | Dockerfile + docker-compose + deploy.sh |

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
