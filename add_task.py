"""
快速添加任务到队列
用法: python add_task.py "任务描述"
"""
import json, os, sys, uuid
from datetime import datetime
from paths import QUEUE_DIR

task_id = "task_" + uuid.uuid4().hex[:8]
task = {
    "id": task_id,
    "description": sys.argv[1] if len(sys.argv) > 1 else "测试任务",
    "status": "pending",
    "priority": "normal",
    "created_at": datetime.now().isoformat(),
    "capabilities_needed": []   # 空=任意节点均可接
}

os.makedirs(QUEUE_DIR, exist_ok=True)
with open(os.path.join(QUEUE_DIR, f"{task_id}.json"), "w", encoding="utf-8") as f:
    json.dump(task, f, ensure_ascii=False, indent=2)

print(f"Task added: {task_id}")
print(f"Description: {task['description']}")