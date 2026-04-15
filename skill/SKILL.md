---
name: clawswarm
description: ClawSwarm — 一只龙虾指挥另一只龙虾。跨设备、跨平台的多 Agent 编排。当用户描述需要多 AI Agent 协同完成复杂任务时触发（如"多 agent"、"spawn"、"orchestrate"、"龙虾"、"swarm"、"multi-agent"）。
metadata: { "openclaw": { "emoji": "🦞" } }
---

# ClawSwarm — 一只龙虾指挥另一只龙虾

## 核心定位

🦞 **一只龙虾 = 一个完整 Agent**（Brain + Hands + Session）

🐉 **ClawSwarm = 龙虾指挥龙虾**（跨设备、跨平台分布式编排）

---

## 什么时候用

当用户说：
- "多 agent 协同完成" / "spawn agents" / "orchestrate"
- "让多个 AI 同时处理" / "龙虾" / "swarm"
- 复杂任务需要分解（"研究 X，分析 Y，写报告 Z"）

**不要用**：单 Agent 能直接搞定的任务。

---

## 架构（龙虾指挥龙虾）

```
用户（自然语言）
    │
    ▼
我（Orchestrator = 主龙虾 🦞）
    │
    ├── sessions_spawn ──→ 子龙虾 Alpha（research）
    │                      ↓ 写入 results/spawn_*.json
    ├── sessions_spawn ──→ 子龙虾 Beta（write）
    │                      ↓ 写入 results/spawn_*.json
    ├── sessions_spawn ──→ 子龙虾 Gamma（code）
    │                      ↓ 写入 results/spawn_*.json
    │
    ├── poll.py ────────→ 等待结果文件
    │
    └── aggregate.py ────→ 聚合 → 最终输出
```

---

## 编排流程

### Step 1 — 分解任务

把复杂任务拆成 2-5 个可并行的子任务。每个子任务：
- 有明确边界
- 可独立执行
- 结果可聚合

### Step 2 — 并行 Spawn

同时调用 `sessions_spawn` 启动多个子龙虾：

```
sessions_spawn(
    message="TASK: [完整任务描述]
结果文件: [results/spawn_标签_时间戳.json]
请执行完成后将结果写入该文件。",
    agent_id="main",
    timeout=120
)
```

### Step 3 — 等待结果

```bash
python scripts/poll.py --label research --timeout 120
python scripts/poll.py --label write --timeout 120
```

### Step 4 — 聚合输出

```bash
python scripts/aggregate.py --labels research,write --output final.json
```

---

## 脚本说明

| 脚本 | 作用 |
|------|------|
| `scripts/spawn.py` | 写任务到队列，返回 task/result 路径 |
| `scripts/poll.py` | 轮询等待结果文件 |
| `scripts/aggregate.py` | 合并多个结果文件 |

---

## 案例

**用户**："调研 AI Agent 最新进展，分析趋势，写一份报告"

**分解**：
- Agent A（research_tech）：搜索最新技术进展
- Agent B（research_prod）：搜索主流产品动态
- Agent C（analysis）：分析趋势（依赖 A+B）
- Agent D（report）：撰写报告（依赖 C）

**执行**：
```
sessions_spawn(A) + sessions_spawn(B)  → 并行
poll.py 等待 A+B 完成
sessions_spawn(C)                      → 顺序
sessions_spawn(D)                      → 顺序
aggregate.py → final.json
```

---

## 设计原则

1. **先分解**：复杂任务必须先拆解，不能直接 spawn
2. **能并行就并行**：独立任务同时执行
3. **文件通信**：Agent 间通过 JSON 文件传递结果
4. **超时控制**：每个 spawn 都设 timeout，避免挂起
5. **聚合为终**：最终答案来自所有子 Agent 输出的聚合

---

## 故障排查

- **Agent 挂起**：检查 timeout，检查结果文件是否写入
- **无输出**：检查 results/ 目录
- **权限错误**：确保目录存在且可写

---

## 研究参考

2026年4月调研结论：

| 发现 | 来源 | 对 ClawSwarm 的意义 |
|------|------|---------------------|
| Anthropic Managed Agents = Brain/Hands/Session 三层 | Anthropic 官方博客 | 验证"龙虾"抽象是正确的 |
| Agent Harness = 独立沙箱运行 | Anthropic Engineering | ClawSwarm 每个龙虾独立 workspace 正是此架构 |
| 2026 多 Agent 分叉四条路线 | CSDN 技术分析 | OpenClaw = 运行时编排，ClawSwarm = 编排的编排 |
| MCP 协议 = 工具扩展标准 | Anthropic/Google | 未来让龙虾间互相调用工具 |
| A2A 协议 = Agent 间通信 | Google | 未来龙虾间直接通信协商 |
