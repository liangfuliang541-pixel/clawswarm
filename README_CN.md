# 🦞 ClawSwarm - 多智能体协同框架

<div align="center">

*[English](README.md)* | *中文版*

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
| [🗺️ 模块索引](MODULES.md) | 代码库模块说明 |

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
