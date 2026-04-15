---
name: clawswarm
description: ClawSwarm — OpenClaw-native multi-agent orchestration. Use when user wants to run complex tasks across multiple AI agents (e.g. "swarm", "orchestrate", "multi-agent", "run this with multiple agents", "spawn agents"). Installs into workspace/skills/clawswarm/.
metadata: { "openclaw": { "emoji": "🦞" } }
---

# ClawSwarm — OpenClaw Multi-Agent Orchestration

## What Is This?

ClawSwarm lets you coordinate multiple OpenClaw agents to work together on complex tasks. Think of it as a "team of AI agents" — each agent specializes in a different part of the task, and they coordinate through file queues.

## When To Use This

Use when the user describes:
- "用多个 agent 完成这个任务" / "spawn agents"
- "让多个 AI 同时处理" / "parallel AI processing"
- "orchestrate" / "multi-agent" / "swarm"
- A task complex enough to benefit from decomposition (e.g., "研究 X，分析 Y，写报告 Z")

**Do NOT use** for simple one-shot tasks that a single agent can handle.

## Architecture

```
You (Orchestrator) ← This is YOU, the AI
    │
    ├── sessions_spawn → sub-agent-1 (research)
    │   tool call          ↓ writes results/spawn_research_*.json
    ├── sessions_spawn → sub-agent-2 (write)
    │   tool call          ↓ writes results/spawn_write_*.json
    ├── sessions_spawn → sub-agent-3 (code)
    │   tool call          ↓ writes results/spawn_code_*.json
    │
    ├── Poll/await all result files
    │
    └── Aggregate → Final output
```

**Key**: `sessions_spawn` is available as an AI tool. You (the AI) can call it directly.

## How To Orchestrate (Step by Step)

When the user asks for a multi-agent task, follow this workflow:

### Step 1 — Decompose
Understand the task and break it into 2-5 independent subtasks.

### Step 2 — Spawn in Parallel
Call `sessions_spawn` as a tool for each independent subtask **simultaneously**.

```
sessions_spawn(
    message="TASK PROMPT: [include full task + result file path]",
    agent_id="main",
    timeout=120
)
```

The spawned agent will:
1. Receive the task prompt
2. Execute it
3. Write result to `results/spawn_<label>_<timestamp>.json`

### Step 3 — Poll for Results
Use `scripts/poll.py` to wait for each result file:

```bash
python scripts/poll.py --label research --timeout 120
python scripts/poll.py --label write --timeout 120
```

### Step 4 — Aggregate
Combine results with `scripts/aggregate.py`:

```bash
python scripts/aggregate.py --labels research,write --output final.json
```

## Available Scripts

### `scripts/poll.py` — Wait for a result
```bash
python scripts/poll.py --label LABEL --timeout SECONDS
```
Polls for a result file matching `results/*<label>*.json`.

### `scripts/aggregate.py` — Combine multiple results
```bash
python scripts/aggregate.py --labels LABEL1,LABEL2 --output FINAL.json
```
Reads all matching result files and writes aggregated output.

## Environment Variables

```bash
# LLM API (for decompose.py and agent prompts)
OPENAI_API_KEY=sk-...        # Optional: for task decomposition
ANTHROPIC_API_KEY=sk-ant-... # Optional: alternative LLM

# ClawSwarm config (optional)
CLAWSWARM_RESULTS_DIR=./results  # Default: ./results
CLAWSWARM_SHARED_DIR=D:/claw/swarm  # Shared folder for multi-machine
```

## Example Workflow

1. User asks: "调研 AI Agent 最新进展，写一份报告"

2. Break down into subtasks:
   - Agent A: 搜索 AI Agent 最新技术进展 → results/spawn_research_tech.json
   - Agent B: 搜索主流 AI Agent 产品 → results/spawn_research_prod.json
   - Agent C: 写报告（依赖 A+B）→ results/spawn_report.json

3. Spawn in parallel (call sessions_spawn for A and B simultaneously):
   ```
   sessions_spawn(message="[Agent A task + result file]", agent_id="main", timeout=120)
   sessions_spawn(message="[Agent B task + result file]", agent_id="main", timeout=120)
   ```

4. Poll for results, then spawn Agent C

5. Aggregate: `aggregate.py --labels research_tech,research_prod,report --output final.json`

6. Return final report to user

## Key Principles

1. **Decompose first** — complex tasks must be broken down before spawning
2. **Parallel where possible** — independent tasks run simultaneously
3. **File-based communication** — agents communicate via JSON files in results/
4. **Timeout everything** — always set reasonable timeouts to avoid hanging
5. **Aggregate last** — final answer combines all sub-agent outputs

## Troubleshooting

- **Agent hangs**: Use --timeout, check result file was written
- **No output**: Check results/ directory for output files
- **API errors**: Ensure LLM API keys are set in environment
- **Permission errors**: Ensure results/ directory exists and is writable
