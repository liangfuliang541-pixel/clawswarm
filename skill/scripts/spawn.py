#!/usr/bin/env python3
"""
ClawSwarm Spawn Script — 通过文件队列 + 轮询实现 agent spawn

架构说明：
    由于 sessions_spawn 只能在 AI session 内通过 tool 调用，
    Python 进程无法直接调用。本脚本采用文件队列方式：

    1. 将任务写入 queue/spawn_<label>_<ts>.json
    2. AI（通过 sessions_spawn）读取任务并执行
    3. 本脚本轮询等待结果写入 results/

用法:
    python spawn.py --prompt "任务描述" --label research_1 [--timeout 120]

输出: results/spawn_<label>_<timestamp>.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── 配置 ──────────────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT = 300
RESULTS_DIR = Path(os.environ.get("CLAWSWARM_RESULTS_DIR", "results"))
QUEUE_DIR = Path(os.environ.get("CLAWSWARM_QUEUE_DIR", "queue"))


def build_agent_prompt(task_prompt: str, result_file: str, task_file: str) -> str:
    """构建发送给 agent 的提示词（包含任务内容和执行说明）"""
    return f"""你是 ClawSwarm 的执行 Agent。

## 任务文件
读取任务详情: {task_file}

## 你的任务
{task_prompt}

## 执行要求
1. 读取 {task_file} 获取完整任务内容
2. 认真完成任务
3. 将结果写入 JSON 文件: {result_file}

## 结果格式
```json
{{
  "status": "success" | "error",
  "output": "执行结果的文字摘要（简洁）",
  "details": {{ ... 详细信息 ... }},
  "completed_at": "{datetime.now(timezone.utc).isoformat()}"
}}
```

请立即开始。"""


def write_task_file(task_prompt: str, label: str, result_file: str) -> tuple[str, str]:
    """将任务写入队列文件，返回 (task_id, task_file_path)"""
    ts = int(time.time())
    task_id = f"spawn_{label}_{ts}"
    task_file = str(QUEUE_DIR / f"{task_id}.json")

    task_data = {
        "task_id": task_id,
        "label": label,
        "prompt": task_prompt,
        "result_file": result_file,
        "task_file": task_file,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    with open(task_file, "w", encoding="utf-8") as f:
        json.dump(task_data, f, ensure_ascii=False, indent=2)

    return task_id, task_file


def poll_for_result(result_file: str, timeout: float, poll_interval: float = 5.0) -> Optional[dict]:
    """轮询等待结果文件"""
    start = time.time()
    while time.time() - start < timeout:
        if Path(result_file).exists():
            try:
                with open(result_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        time.sleep(poll_interval)
    return None


def spawn_agent(
    task_prompt: str,
    label: str,
    timeout: float = DEFAULT_TIMEOUT,
    results_dir: Path = None,
) -> dict:
    """
    通过文件队列方式启动 agent：

    1. 写入任务到 queue/
    2. 轮询等待 results/ 中的结果

    注意：需要 AI（sessions_spawn）读取 queue/ 并执行任务。
    本脚本只负责写任务文件和轮询结果。
    """
    if results_dir is None:
        results_dir = RESULTS_DIR

    ts = int(time.time())
    spawn_id = f"spawn_{label}_{ts}"
    result_file = str(results_dir / f"{spawn_id}.json")

    # 构建 agent 提示词
    task_id, task_file = write_task_file(task_prompt, label, result_file)
    agent_prompt = build_agent_prompt(task_prompt, result_file, task_file)

    # 写 agent 提示词（供 AI 调用 sessions_spawn 时读取）
    prompt_file = str(QUEUE_DIR / f"{spawn_id}_prompt.txt")
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(agent_prompt)

    # 写 spawn 元信息
    spawn_meta = {
        "spawn_id": spawn_id,
        "task_id": task_id,
        "task_file": task_file,
        "prompt_file": prompt_file,
        "result_file": result_file,
        "label": label,
        "status": "queued",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            f"任务已写入 {task_file}。\n"
            f"Agent 提示词已写入 {prompt_file}。\n"
            f"请使用 sessions_spawn 调用 agent 读取并执行任务。\n"
            f"结果将写入 {result_file}。\n"
            f"然后轮询 {result_file} 获取结果。"
        ),
    }

    # 写 meta 文件
    meta_file = str(QUEUE_DIR / f"{spawn_id}_meta.json")
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(spawn_meta, f, ensure_ascii=False, indent=2)

    # 立即尝试轮询结果（如果 agent 已在线处理）
    result = poll_for_result(result_file, timeout=5.0, poll_interval=1.0)
    if result:
        return {
            "spawn_id": spawn_id,
            "status": result.get("status", "success"),
            "output": result.get("output", ""),
            "details": result,
            "result_file": result_file,
            "source": "immediate_poll",
        }

    # 返回 meta 信息（表示任务已入队，等待 AI 处理）
    return {
        "spawn_id": spawn_id,
        "status": "queued",
        "task_file": task_file,
        "prompt_file": prompt_file,
        "result_file": result_file,
        "meta_file": meta_file,
        "agent_prompt": agent_prompt,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            f"任务已入队到 {task_file}。\n"
            "AI 需要通过 sessions_spawn 读取并执行。\n"
            "轮询结果文件: poll.py --label {label} --timeout {int(timeout)}"
        ),
    }


# ── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ClawSwarm Agent Spawner (file-queue mode)")
    parser.add_argument("--prompt", required=True, help="Agent 执行任务")
    parser.add_argument("--label", required=True, help="唯一标签")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"超时秒数 (默认: {DEFAULT_TIMEOUT})")
    parser.add_argument("--results-dir", default=None, help=f"结果目录 (默认: {RESULTS_DIR})")

    args = parser.parse_args()
    results_dir_override = Path(args.results_dir) if args.results_dir else None

    result = spawn_agent(
        task_prompt=args.prompt,
        label=args.label,
        timeout=args.timeout,
        results_dir=results_dir_override,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
