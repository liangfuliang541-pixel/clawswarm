"""
ClawSwarm Spawn Manager — sub-agent spawn 管理器

Orchestrator 的 _schedule() 方法通过以下流程 spawn agent:
  1. 调用 spawn_via_agent(task, task_id, timeout, label) 
     → 写入 swarm_data/spawn_queue/{spawn_id}.json
  2. LLM 在后续 turn 中会检查 spawn_queue/ 目录，
     调用 sessions_spawn 处理队列中的请求，
     并将结果（含 childSessionKey）写入 spawn_results/
  3. orchestrator 下次调用 check_spawn_results() 检查是否有完成的结果

核心文件:
  - swarm_data/spawn_queue/{spawn_id}.json   # 待处理 spawn 请求
  - swarm_data/spawn_results/{spawn_id}.json # spawn 结果
"""
import json, time
from pathlib import Path
from typing import Dict, Optional, Tuple

SPAWN_QUEUE_DIR   = Path(__file__).parent / "swarm_data" / "spawn_queue"
SPAWN_RESULTS_DIR = Path(__file__).parent / "swarm_data" / "spawn_results"

SPAWN_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
SPAWN_RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# 内存中的 spawn 追踪（orchestrator 进程内）
_pending_spawns: Dict[str, Dict] = {}


def spawn_via_agent(task: str, task_id: str = None, timeout: int = 120,
                    label: str = None) -> Tuple[str, Dict]:
    """
    将 spawn 请求写入队列文件（由 LLM 通过 sessions_spawn 处理）。
    
    返回: (spawn_id, meta_dict)
    spawn_id 用于后续 check_spawn_results() 查询结果
    """
    spawn_id = task_id or f"sp_{int(time.time()*1000)}"
    label = label or f"orchestrator-{spawn_id}"

    req = {
        "spawn_id": spawn_id,
        "task": task,
        "label": label,
        "timeout": timeout,
        "submitted_at": time.time(),
        "status": "pending",
    }
    req_file = SPAWN_QUEUE_DIR / f"{spawn_id}.json"
    with open(req_file, "w", encoding="utf-8") as f:
        json.dump(req, f, ensure_ascii=False, indent=2)

    meta = {
        "spawn_id": spawn_id,
        "label": label,
        "timeout": timeout,
        "status": "pending",
    }
    _pending_spawns[spawn_id] = meta
    return spawn_id, meta


def check_spawn_results(spawn_ids: list = None) -> Dict[str, Dict]:
    """
    检查 spawn 结果（非阻塞，只检查已存在的文件）。
    
    参数:
        spawn_ids: 要检查的 spawn_id 列表，None 表示检查所有 pending 的
    
    返回:
        {spawn_id: {"status": "...", "result": "...", "childSessionKey": "..."}}
    """
    results = {}
    to_check = spawn_ids or list(_pending_spawns.keys())
    
    for sid in to_check:
        result_file = SPAWN_RESULTS_DIR / f"{sid}.json"
        if result_file.exists():
            try:
                with open(result_file, encoding="utf-8") as f:
                    data = json.load(f)
                results[sid] = {
                    "status": data.get("status", "unknown"),
                    "result": data.get("result"),
                    "childSessionKey": data.get("childSessionKey"),
                    "elapsed": time.time() - data.get("submitted_at", time.time()),
                }
                # 更新内存追踪
                if sid in _pending_spawns:
                    _pending_spawns[sid]["status"] = data.get("status", "done")
            except Exception:
                pass
    
    return results


def complete_spawn(spawn_id: str, child_session_key: str = None, result: str = None,
                  status: str = "success", error: str = None):
    """
    LLM 调用 sessions_spawn 完成后，调用此函数写入结果。

    写入两个位置：
    1. SPAWN_RESULTS_DIR/{spawn_id}.json  - spawn_manager 专用
    2. RESULTS_DIR/r_{spawn_id}.json       - ResultWatcher 可以检测到
    """
    data = {
        "spawn_id": spawn_id,
        "status": status,
        "childSessionKey": child_session_key,
        "result": result,
        "completed_at": time.time(),
    }
    if error:
        data["error"] = error

    # 写入 spawn 专用结果目录
    result_file = SPAWN_RESULTS_DIR / f"{spawn_id}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 写入 Results_DIR（ResultWatcher 会检测这个目录）
    from pathlib import Path
    RESULTS_DIR = Path(__file__).parent / "swarm_data" / "results"
    results_file = RESULTS_DIR / f"r_{spawn_id}.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump({
            "task_id": spawn_id,
            "status": status,
            "result": result,
        }, f, ensure_ascii=False, indent=2)

    # 删除队列请求
    req_file = SPAWN_QUEUE_DIR / f"{spawn_id}.json"
    if req_file.exists():
        req_file.unlink(missing_ok=True)

    # 更新内存追踪
    if spawn_id in _pending_spawns:
        _pending_spawns[spawn_id]["status"] = status
        _pending_spawns[spawn_id]["childSessionKey"] = child_session_key


def get_pending_spawns() -> list:
    """返回所有待处理的 spawn 请求"""
    pending = []
    for f in SPAWN_QUEUE_DIR.glob("*.json"):
        try:
            with open(f, encoding="utf-8") as fp:
                pending.append(json.load(fp))
        except Exception:
            pass
    return sorted(pending, key=lambda x: x.get("submitted_at", 0))


def read_spawn_result(spawn_id: str) -> Optional[Dict]:
    """读取指定 spawn 的结果文件"""
    result_file = SPAWN_RESULTS_DIR / f"{spawn_id}.json"
    if result_file.exists():
        try:
            with open(result_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None
