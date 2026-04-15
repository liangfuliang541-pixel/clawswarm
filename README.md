# 🦞 ClawSwarm - Multi-Agent Orchestration Framework

<div align="center">

**[English](README.md)** | **[中文](README_CN.md)**

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
| 💾 **Persistence** | File-based queue survives restarts |
| 🌐 **Cross-Machine** | Works across LAN via shared storage |
| 🔄 **Fault Tolerance** | Auto-retry failed tasks |
| 🔌 **OpenClaw Native** | Seamless OpenClaw Agent integration |
| 🌍 **Bilingual** | Full English + Chinese documentation |

---

## 🚀 Quick Start

### Install

```bash
git clone https://github.com/liangfuliang541-pixel/clawswarm.git
cd clawswarm
```

### Start Nodes

```bash
# Start 3-node demo cluster
python start_cluster.py

# Or start manually
python swarm_node.py claw_alpha search write code
python swarm_node.py claw_beta read write
python swarm_node.py claw_gamma search analyze report
```

### Add Tasks

```bash
python swarm_scheduler.py add "Research latest AI trends" --type research
```

### Check Status

```bash
python swarm_scheduler.py status
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
