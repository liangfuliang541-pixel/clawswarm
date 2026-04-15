import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json, os, uuid
from datetime import datetime
from paths import QUEUE_DIR

tasks = [
    "搜索今天深圳天气",
    "整理桌面文件，归类到 D:\claw\workspace",
    "分析昨天的工作日志，写一个简短的报告"
]

os.makedirs(QUEUE_DIR, exist_ok=True)

for desc in tasks:
    task_id = "task_" + uuid.uuid4().hex[:8]
    task = {
        "id": task_id,
        "description": desc,
        "status": "pending",
        "priority": "normal",
        "created_at": datetime.now().isoformat()
    }
    path = os.path.join(QUEUE_DIR, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    print(f"Added: {task_id} -> {desc}")

print(f"\nTotal {len(tasks)} tasks in queue. Nodes will pick them up shortly.")