#!/usr/bin/env python3
"""
ClawSwarm Quick Start — 快速上手示例

运行方法:
    python examples/01_quickstart.py

本脚本展示:
1. 提交任务到队列
2. 轮询等待执行
3. 读取结果
"""

import json
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

QUEUE_DIR = BASE_DIR / "swarm_data" / "queue"
RESULTS_DIR = BASE_DIR / "swarm_data" / "results"


def submit_task(prompt: str, task_type: str = "general", priority: int = 5) -> str:
    """提交任务到队列，返回 task_id"""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    task_id = f"task_{int(time.time())}"
    task = {
        "id": task_id,
        "type": task_type,
        "prompt": prompt,
        "priority": priority,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    task_file = QUEUE_DIR / f"{task_id}.json"
    with open(task_file, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)

    print(f"[+] Task submitted: {task_id} -> {task_file}")
    return task_id


def poll_task(node_id: str = "quickstart_node") -> dict:
    """轮询获取任务"""
    for f in sorted(QUEUE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            with open(f, encoding="utf-8") as fp:
                task = json.load(fp)
            # 移动到 in_progress
            print(f"[>] Polled: {task['id']} from {f.name}")
            return task
        except Exception:
            pass
    return None


def poll_result(label: str, timeout: int = 60) -> dict:
    """轮询等待结果文件"""
    start = time.time()
    while time.time() - start < timeout:
        for rf in RESULTS_DIR.glob(f"r_*{label}*.json"):
            try:
                with open(rf, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        time.sleep(2)
    return {"status": "timeout", "error": f"No result for {label} in {timeout}s"}


def complete_task(task_id: str, result: dict, node_id: str):
    """完成任务，写入结果文件"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / f"r_{task_id}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[+] Result written: {result_file}")


def example_submit_and_poll():
    """示例：提交任务并轮询结果"""
    print("\n" + "=" * 50)
    print("Example: Submit & Poll")
    print("=" * 50)

    task_id = submit_task(
        prompt="Hello from ClawSwarm quickstart! What is 2+2?",
        task_type="general",
        priority=5,
    )

    print(f"\nTask {task_id} submitted. Simulating execution...")
    time.sleep(1)

    result = {
        "task_id": task_id,
        "status": "success",
        "output": "2 + 2 = 4 (from ClawSwarm executor simulation)",
        "executed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    complete_task(task_id, result, "quickstart_node")

    print("\nPoll result:")
    poll_res = poll_result(task_id.replace("task_", ""), timeout=5)
    print(json.dumps(poll_res, indent=2, ensure_ascii=False))


def example_batch_submit():
    """示例：批量提交任务"""
    print("\n" + "=" * 50)
    print("Example: Batch Submit")
    print("=" * 50)

    prompts = [
        "Search for the latest AI news",
        "Analyze the top 3 AI trends in 2026",
        "Write a summary of Claude's managed agents",
    ]

    task_ids = []
    for p in prompts:
        tid = submit_task(prompt=p, priority=7)
        task_ids.append(tid)

    print(f"\nSubmitted {len(task_ids)} tasks:")
    for tid in task_ids:
        print(f"  - {tid}")


def example_read_results():
    """示例：读取结果目录"""
    print("\n" + "=" * 50)
    print("Example: Read Results")
    print("=" * 50)

    results = list(RESULTS_DIR.glob("*.json"))
    print(f"Found {len(results)} result files in {RESULTS_DIR}")

    for rf in sorted(results, key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
        try:
            with open(rf, encoding="utf-8") as f:
                data = json.load(f)
            print(f"\n  {rf.name}:")
            print(f"    status: {data.get('status')}")
            output = data.get('output', '')[:80]
            print(f"    output: {output}...")
        except Exception as e:
            print(f"  {rf.name}: ERROR - {e}")


if __name__ == "__main__":
    print("ClawSwarm Quick Start")
    print(f"Queue dir: {QUEUE_DIR}")
    print(f"Results dir: {RESULTS_DIR}")

    example_submit_and_poll()
    example_batch_submit()
    example_read_results()

    print("\n" + "=" * 50)
    print("Done! Next: python examples/02_parallel.py")
    print("=" * 50)
