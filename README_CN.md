# 🦞 ClawSwarm - 多智能体协同框架

<div align="center">

*[English](README.md)* | *中文版* | *[关于](ABOUT_CN.md)*

*让多个 AI Agent 像龙虾群一样协同工作*

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-green.svg)](https://www.python.org/)
[![GitHub stars](https://img.shields.io/github/stars/liangfuliang541-pixel/clawswarm?style=social)](https://github.com/liangfuliang541-pixel/clawswarm/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/liangfuliang541-pixel/clawswarm?style=social)](https://github.com/liangfuliang541-pixel/clawswarm/network)
[![GitHub issues](https://img.shields.io/github/issues/liangfuliang541-pixel/clawswarm)](https://github.com/liangfuliang541-pixel/clawswarm/issues)

*由 [liangfuliang541-pixel](https://github.com/liangfuliang541-pixel) 用 ❤️ 构建*

</div>

---

## ⭐ 为什么选择 ClawSwarm?

| 特性 | ClawSwarm | crewAI | AutoGen |
|------|-----------|--------|---------|
| **零配置启动** | ✅ 纯 JSON | ❌ 需写 Python | ❌ 需写 Python |
| **无数据库依赖** | ✅ 文件队列 | ❌ 外部服务 | ❌ 外部服务 |
| **OpenClaw 原生** | ✅ 深度集成 | ❌ | ❌ |
| **跨机器部署** | ✅ SMB/共享文件夹 | ❌ | ❌ |
| **离线容错** | ✅ 本地队列 | ❌ | ❌ |
| **语音控制** | ✅ 通过 OpenClaw | ❌ | ❌ |

> **一句话**: ClawSwarm 是协调多机器上多个 AI Agent 最简单的方式，无需任何基础设施。

---

## ✨ 特性

| 特性 | 说明 |
|------|------|
| 🦞 **多节点协同** | 一个主 Agent 指挥多个节点 Agent |
| 🧠 **智能调度** | 根据节点能力自动分配任务 |
| 📊 **结果聚合** | 收集并合并所有节点的结果 |
| 💾 **持久化** | 基于文件的队列，重启不丢失 |
| 🌐 **跨机器** | 局域网共享存储，支持多机器 |
| 🔄 **容错** | 失败任务自动重试，stale 任务自动恢复 |
| 🔌 **OpenClaw 原生** | 通过 sessions_spawn 无缝集成 OpenClaw Agent |
| 🌍 **双语支持** | 完整英文 + 中文文档 |
| ⏸️ **人工审批** | 关键任务支持 HITL 检查点审批 |
| 📡 **OpenTelemetry** | 分布式追踪 + Prometheus 指标 |
| 🔔 **WebSocket 事件** | 实时任务/检查点事件推送 |
| 🖥️ **Dashboard** | FastAPI + WebSocket 实时监控面板 |
| 🤖 **MCP Server** | 让其他 Agent 通过 MCP 协议调用 ClawSwarm |
| 🚢 **生产就绪** | Dockerfile + docker-compose + deploy.sh |

---

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/liangfuliang541-pixel/clawswarm.git
cd clawswarm
pip install -r requirements.txt
```

### 启动 Master + 2 节点

```bash
# 方式一：部署脚本（推荐本地）
./deploy.sh install-deps
./deploy.sh local

# 方式二：Docker Compose（推荐部署）
cp .env.template .env   # 编辑 .env 填入 API key
docker compose up -d

# 方式三：手动 CLI
python cli.py start-cluster                        # 启动3节点演示集群
python cli.py add-task "调研2026年AI最新进展"         # 添加任务
python cli.py status                               # 查看状态
```

### 添加任务

```bash
# CLI 方式
python cli.py add-task "调研AI最新进展" --type research --priority 5

# REST API 方式（master 运行中）
curl -X POST http://localhost:5000/tasks \
  -H "Content-Type: application/json" \
  -d '{"text":"调研AI最新进展","type":"research","priority":5}'
```

### 查看状态

```bash
python cli.py status
# 或通过 REST API
curl http://localhost:5000/tasks
```

### Docker 部署

```bash
cp .env.template .env
docker compose up -d
# Master API:  http://localhost:5000
# Event WS:    ws://localhost:8765
# Node Alpha:  http://localhost:5171
# Node Beta:   http://localhost:5172
```

---

## 📖 文档

| 文档 | 说明 |
|------|------|
| [📚 架构设计](docs/ARCHITECTURE.md) | 核心技术架构 |
| [🗺️ 演进路线](docs/EVOLUTION.md) | 从 MVP 到产品化规划 |
| [📝 任务格式](docs/TASK-FORMAT.md) | 任务 JSON 规范 |
| [⚙️ 节点配置](docs/NODE-CONFIG.md) | 节点配置指南 |
| [🔌 API 参考](docs/API.md) | 命令行和 Python API |
| [🚀 部署指南](docs/DEPLOY.md) | Docker 和本地部署 |
| [🦞 关于](ABOUT_CN.md) | 项目故事、设计理念与发展路线 |
| [🗺️ 模块索引](MODULES_CN.md) | 代码库模块说明 |
| [🧠 OpenClaw Skill](skill/) | 一键安装到 OpenClaw |
| [🤖 MCP Server](mcp_server.py) | MCP 协议接入 |

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────┐
│              主 Agent (Master)               │
│  ┌─────────┐ ┌─────────┐ ┌─────────────┐   │
│  │ 任务分发 │ │ 结果聚合 │ │  健康监测   │   │
│  └────┬────┘ └────▲────┘ └──────┬──────┘   │
└───────┼───────────┼──────────────┼──────────┘
        │           │              │
        ▼           │              ▼
   ┌─────────────────────────────────────┐
   │         共享存储 (queue/)           │
   └─────────────────────────────────────┘
        ▲           ▲              ▲
        │           │              │
┌───────┴───┐ ┌────┴────┐ ┌──────┴──────┐
│  节点 1   │ │ 节点 2   │ │   节点 N    │
│ (搜索)    │ │ (写作)   │ │   (代码)    │
└───────────┘ └─────────┘ └─────────────┘
```

---

## 🖥️ Dashboard

Web UI 实时监控面板，展示龙虾集群状态、任务 DAG、执行结果。

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

**REST API**：
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

**跨 Agent 调用**：

Claude Code、Cursor、CodeBuddy 等 Agent 可通过 MCP 协议直接调用：

```bash
# 已注册到 mcporter
mcporter call clawswarm.clawswarm_submit prompt="test"
```

---

## 📚 Examples

```bash
python examples/01_quickstart.py   # 快速上手：提交 + 轮询
python examples/02_parallel.py     # 并行任务：多任务 + 聚合
python examples/04_mcp_demo.py     # MCP 协议调用示例
```

---

## 🤝 贡献

欢迎贡献！详见 [贡献指南](CONTRIBUTING_CN.md)。

- 🐛 报告问题
- 💡 提出新功能
- 📝 提交代码
- 🌐 翻译文档

---

## 📄 许可证

**AGPL v3** - 见 [LICENSE](LICENSE)

商业授权请联系：liangfuliang541@gmail.com

---

## 🌍 社区

- 📖 [文档](docs/)
- 🐛 [问题反馈](https://github.com/liangfuliang541-pixel/clawswarm/issues)
- 💬 [讨论区](https://github.com/liangfuliang541-pixel/clawswarm/discussions)

---

<div align="center">

**⭐ 在 GitHub 上给我们星标！** | **让 AI Agent 像龙虾群一样协同工作** 🦞

</div>
