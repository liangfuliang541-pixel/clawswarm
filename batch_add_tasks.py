import sys
sys.path.insert(0, r"D:\claw\swarm")
from add_task import *

tasks = [
    "搜索今天深圳天气",
    "整理桌面文件，归类到 D:\claw\workspace",
    "分析昨天的工作日志，写一个简短的报告"
]

# 重新实现，不依赖 add_task.py 的 sys.argv
import json, os, uuid
from datetime import datetime

BASE  = r"D:\claw\swarm"
QUEUE = os.path.join(BASE, "queue")
os.makedirs(QUEUE, exist_ok=True)

for desc in tasks:
    task_id = "task_" + uuid.uuid4().hex[:8]
    task = {
        "id": task_id,
        "description": desc,
        "status": "pending",
        "priority": "normal",
        "created_at": datetime.now().isoformat()
    }
    path = os.path.join(QUEUE, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    print(f"Added: {task_id} -> {desc}")

print(f"\nTotal {len(tasks)} tasks in queue. Nodes will pick them up shortly.")