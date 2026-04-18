# 🦞 ClawSwarm - 多智能体协同平台

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.12.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.8+-green" alt="Python">
  <img src="https://img.shields.io/badge/tests-164%20passed-success" alt="Tests">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License">
  <img src="https://img.shields.io/badge/LOC-23k-blueviolet" alt="LOC">
</p>

<div align="center">

*[English](README.md)* | *中文版* | *[关于](ABOUT_CN.md)*

*让多个 AI Agent 像龙虾群一样协同工作*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-green.svg)](https://www.python.org/)
[![GitHub stars](https://img.shields.io/github/stars/liangfuliang541-pixel/clawswarm?style=social)](https://github.com/liangfuliang541-pixel/clawswarm/stargazers)

*由 [liangfuliang541-pixel](https://github.com/liangfuliang541-pixel) 用 ❤️ 构建*

</div>

---

## ⭐ 为什么选择 ClawSwarm?

| 特性 | ClawSwarm | crewAI | AutoGen |
|------|-----------|--------|---------|
| **零配置启动** | ✅ 纯 JSON | ❌ 需写 Python | ❌ 需写 Python |
| **无数据库依赖** | ✅ 文件队列 | ❌ 外部服务 | ❌ 外部服务 |
| **OpenClaw 原生** | ✅ 深度集成 | ❌ | ❌ |
| **跨机器部署** | ✅ Hub-Spoke + SMB | ❌ | ❌ |
| **异构 Agent 适配** | ✅ Hermes/Evolver/OpenClaw | ❌ | ❌ |
| **离线容错** | ✅ 本地队列 | ❌ | ❌ |
| **语音控制** | ✅ 通过 OpenClaw | ❌ | ❌ |

> **一句话**: ClawSwarm 是协调多机器上多个 AI Agent 最简单的方式，无需任何基础设施。

---

## ✨ 特性

- 🦞 **多智能体编排** — 并行调度和协调多个 AI Agent
- 🧠 **能力感知调度** — 根据节点能力智能分配任务
- 🔀 **DAG 工作流** — 构建依赖图，最大化并行执行
- 🌐 **Hub-Spoke 网络** — 无需 tunnel/公网 IP 的跨机器通信
- 🔌 **异构 Agent 适配器** — 接入 Hermes (ACP)、Evolver、OpenClaw Agent
- 🤖 **MCP Server** — 将 ClawSwarm 暴露为 MCP 工具供其他 Agent 调用
- 💬 **ClawChat** — Agent 间实时聊天，SQLite 持久存储 + WebSocket 推送
- 🖥️ **Web 监控面板** — WebSocket 实时推送，监控集群状态，内置聊天面板
- 📊 **OpenTelemetry** — 开箱即用的生产级可观测性
- 🔒 **沙箱安全** — 路径白名单、命令黑名单、审计日志
- ✅ **人工审批点** — 关键任务支持 HITL 人工确认
- 🐳 **Docker 就绪** — 完整 Docker + Docker Compose 部署支持
- 🔄 **零依赖** — Phase 1 采用文件队列，无需消息队列
- 🏢 **多租户** — 命名空间隔离、RBAC 权限、资源配额
- 🔐 **联邦学习** — 分布式 AI 训练（FedAvg/FedProx 聚合）
- 🌐 **边缘计算** — IoT 设备适配器（HTTP/MQTT/WebSocket/CoAP）
- ⚡ **自动扩缩容** — 基于负载弹性伸缩、冷却策略

---

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/liangfuliang541-pixel/clawswarm.git
cd clawswarm
pip install -r requirements.txt
```

### 启动 Hub + Agent 节点

```bash
# 启动 Hub（嵌入 master_api.py）
python master_api.py --port 50010 --hub-port 18080

# 启动本地 Agent 节点
python networking.py agent --hub-url http://localhost:18080 --agent-id local-01

# 启动 Hermes Agent 节点（ACP 适配器）
python networking.py agent --hub-url http://localhost:18080 --agent-id hermes-01 \
  --adapter-type hermes \
  --adapter-config '{"hermes_bin":"hermes","model":"qwen2.5:72b"}'

# 通过 HubClient 下发任务
python networking.py client --hub-url http://localhost:18080 \
  --task "Fetch https://httpbin.org/json" --task-type fetch
```

### 或使用经典文件队列

```bash
# 方式一：部署脚本（推荐本地）
./deploy.sh install-deps && ./deploy.sh local

# 方式二：Docker Compose（推荐部署）
cp .env.template .env && docker compose up -d

# 方式三：手动 CLI
python cli.py start-cluster
python cli.py add-task "调研2026年AI最新进展"
python cli.py status
```

---

## 🏗️ 架构

### Hub-Spoke 模型（跨机器）

```
┌──────────────────────────────────────────────┐
│              Hub (port 18080)                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Agent    │ │ Task     │ │ Result       │ │
│  │ Registry │ │ Queue    │ │ Store        │ │
│  └────┬─────┘ └────▲─────┘ └──────┬───────┘ │
└───────┼─────────────┼──────────────┼─────────┘
        │             │              │
        │    HTTP 轮询 + 提交结果     │
        │             │              │
┌───────┴─────┐ ┌────┴─────┐ ┌──────┴───────┐
│ OpenClaw    │ │ Hermes   │ │ Evolver      │
│ Agent       │ │ (ACP)    │ │ (Skill)      │
│ (原生)      │ │ 适配器   │ │ 适配器       │
└─────────────┘ └──────────┘ └──────────────┘
```

### 本地文件队列模型

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

## 🔌 Agent 适配器

ClawSwarm 通过可插拔的适配器层支持异构 Agent 类型：

| 适配器 | 协议 | 用途 |
|--------|------|------|
| `openclaw` | HTTP Hub 轮询 | 原生 OpenClaw Agent |
| `hermes` | ACP (stdin/stdout JSON-RPC 2.0) | Nous Research Hermes Agent |
| `evolver` | sessions_send / 文件轮询 | OpenClaw Evolver Skill Agent |

```python
from agent_adapter import get_adapter

# 创建 Hermes 适配器
adapter = get_adapter("hermes", "hermes-01", {
    "hermes_bin": "hermes",
    "model": "qwen2.5:72b",
    "capabilities": ["code", "reason"]
})
adapter.start()
result = await adapter.execute({"prompt": "写一个斐波那契函数"})
```

---

## 🖥️ Dashboard

Web UI 实时监控面板，展示龙虾集群状态、任务 DAG、执行结果。

```bash
python dashboard/dashboard.py --port 5000
# 打开 http://localhost:5000
```

**功能**：节点状态面板、任务 DAG 可视化、实时事件流、内置聊天面板、自然语言任务提交。

---

## 🤖 MCP Server

让其他 Agent 通过 MCP 协议调用 ClawSwarm。

```bash
python mcp_server.py
# 或通过 mcporter：mcporter call clawswarm.clawswarm_status
```

**MCP Tools**：`clawswarm_spawn`、`clawswarm_poll`、`clawswarm_submit`、`clawswarm_status`、`clawswarm_nodes`、`clawswarm_aggregate`、`clawswarm_dead_letter`、`clawswarm_health`

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
| [🗺️ 模块索引](MODULES_CN.md) | 代码库模块说明 |
| [🧠 OpenClaw Skill](skill/) | 一键安装到 OpenClaw |
| [🦞 关于](ABOUT_CN.md) | 项目故事、设计理念与发展路线 |

---

## 🤝 贡献

欢迎贡献！详见 [贡献指南](CONTRIBUTING_CN.md)。

## 📄 许可证

**MIT** - 见 [LICENSE](LICENSE)

---

<div align="center">

**⭐ 在 GitHub 上给我们星标！** | **让 AI Agent 像龙虾群一样协同工作** 🦞

</div>
