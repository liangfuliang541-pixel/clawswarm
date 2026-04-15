#!/usr/bin/env python3
"""
ClawSwarm Parallel Tasks — 并行任务示例

运行方法:
    python examples/02_parallel.py

本脚本展示:
1. 并行提交多个任务
2. 并行执行（通过 asyncio）
3. 轮询等待所有结果
4. 聚合输出
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

QUEUE_DIR = BASE_DIR / "swarm_data" / "queue"
RESULTS_DIR = BASE_DIR / "swarm_data" / "results"


def submit_task(prompt: str, label: str, priority: int = 5) -> str:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    task_id = f"task_{label}_{ts}"
    task = {
        "id": task_id,
        "label": label,
        "prompt": prompt,
        "priority": priority,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(QUEUE_DIR / f"{task_id}.json", "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    return task_id


def poll_result(label: str, timeout: int = 60) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        for rf in sorted(RESULTS_DIR.glob(f"r_*{label}*.json"), key=lambda p: p.stat().st_mtime):
            try:
                with open(rf, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        time.sleep(1)
    return {"status": "timeout", "label": label}


def simulate_execution(task_id: str, label: str):
    """模拟执行任务（Demo 模式下替代真实的 executor）"""
    time.sleep(0.5)  # 模拟处理时间
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / f"r_{task_id}.json"
    result = {
        "task_id": task_id,
        "label": label,
        "status": "success",
        "output": f"[Simulated] Task '{label}' executed successfully.",
        "executed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def aggregate_results(labels: list) -> dict:
    """聚合多个标签的结果"""
    aggregated = {}
    for label in labels:
        res = poll_result(label, timeout=5)
        aggregated[label] = res.get("output", res.get("error", ""))
    return aggregated


def example_parallel_submit():
    """示例：并行提交 + 执行"""
    print("\n" + "=" * 50)
    print("Example: Parallel Tasks")
    print("=" * 50)

    tasks = [
        ("research_ai", "Research latest AI agent frameworks in 2026", 8),
        ("analyze_trends", "Analyze top 3 AI trends this month", 7),
        ("compare_tools", "Compare Claude, GPT, Gemini agent capabilities", 6),
    ]

    print("\n[1] Submitting 3 tasks in parallel...")
    task_ids = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(submit_task, prompt, label, priority): (label, prompt)
            for label, prompt, priority in tasks
        }
        for future in as_completed(futures):
            label, _ = futures[future]
            task_id = future.result()
            task_ids.append((label, task_id))
            print(f"    Submitted: {label} -> {task_id}")

    print("\n[2] Executing tasks in parallel (simulated)...")
    with ThreadPoolExecutor(max_workers=3) as executor:
        exec_futures = {
            executor.submit(simulate_execution, tid, label): label
            for label, tid in task_ids
        }
        for future in as_completed(exec_futures):
            label = exec_futures[future]
            result = future.result()
            print(f"    Completed: {label} -> {result['status']}")

    print("\n[3] Aggregating results...")
    labels = [label for label, _ in task_ids]
    aggregated = aggregate_results(labels)

    print("\nAggregated Output:")
    print("-" * 40)
    for label, output in aggregated.items():
        print(f"\n  [{label}]")
        print(f"  {output[:100]}...")
    print("-" * 40)

    return aggregated


if __name__ == "__main__":
    print("ClawSwarm Parallel Tasks Example")
    print(f"Queue: {QUEUE_DIR}")
    print(f"Results: {RESULTS_DIR}")

    result = example_parallel_submit()

    print("\n" + "=" * 50)
    print("Parallel execution complete!")
    print(f"Next: python examples/04_mcp_demo.py (MCP server)")
    print("=" * 50)
