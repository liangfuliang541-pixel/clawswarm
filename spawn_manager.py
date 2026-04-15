"""
ClawSwarm Spawn Manager — sub-agent spawn 管理器

Orchestrator 的 _schedule() 方法通过以下流程 spawn agent:
  1. 调用 spawn_via_agent(task, task_id, timeout, label) 
     → 写入 swarm_data/spawn_queue/{spawn_id}.json
     → 启动后台线程，通过 openclaw CLI spawn 处理 agent
  2. 后台 agent 调用 sessions_spawn，执行任务，结果写入 spawn_results/
  3. spawn_via_agent() 轮询等待结果文件，超时则标记失败

核心文件:
  - swarm_data/spawn_queue/{spawn_id}.json   # 待处理 spawn 请求
  - swarm_data/spawn_results/{spawn_id}.json # spawn 结果
"""
import json
import time
import threading
import subprocess
import sys
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 目录配置
SPAWN_QUEUE_DIR   = Path(__file__).parent / "swarm_data" / "spawn_queue"
SPAWN_RESULTS_DIR = Path(__file__).parent / "swarm_data" / "spawn_results"

SPAWN_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
SPAWN_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# OpenClaw CLI 路径
OPENCLAW_CMD = str(Path(sys.executable).parent / "openclaw.cmd")
if not Path(OPENCLAW_CMD).exists():
    OPENCLAW_CMD = "openclaw"  # fallback to PATH

# 线程池，用于后台 spawn 处理
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="spawn_worker")


# ── 内存追踪 ──────────────────────────────────────────────────────────────

_pending_spawns: Dict[str, Dict] = {}


# ── 核心 API ──────────────────────────────────────────────────────────────

def spawn_via_agent(task: str, task_id: str = None, timeout: int = 120,
                    label: str = None) -> Tuple[str, Dict]:
    """
    将 spawn 请求写入队列，并通过后台线程触发 sessions_spawn。
    
    流程:
      1. 写队列文件
      2. 启动后台线程 → openclaw sessions spawn → 写结果
      3. 轮询等待结果（最多 timeout 秒）
      4. 返回 (spawn_id, meta)
    
    返回: (spawn_id, meta_dict)
    """
    spawn_id = task_id or f"sp_{int(time.time()*1000)}"
    label = label or f"orch-{spawn_id}"
    timeout = max(timeout, 30)  # 至少等 30 秒

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

    # 启动后台线程处理 spawn（不等完成）
    _executor.submit(_spawn_worker, spawn_id, task, label, timeout)

    return spawn_id, meta


def _spawn_worker(spawn_id: str, task: str, label: str, timeout: int):
    """
    后台线程处理：监控队列 → 通过 Gateway HTTP API 调用 sessions
    注意：sessions_spawn 工具只能通过 LLM 调用，这里通过 Gateway HTTP API 模拟。
    """
    from pathlib import Path as PP
    project_root = Path(__file__).parent.parent.resolve()
    
    GATEWAY_URL = "http://127.0.0.1:28789"
    TOKEN = os.environ.get("CLAWSWARM_GATEWAY_TOKEN", "92ea9d9f6b4c8fc829486f0e736f721e4280739c94af128a")
    
    try:
        import urllib.request, urllib.error
        
        def http_post(path, data):
            req = urllib.request.Request(
                f"{GATEWAY_URL}{path}",
                data=json.dumps(data).encode(),
                headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                return {"error": f"HTTP {e.code}: {e.reason}"}
        
        # 1. 通过 Gateway HTTP API 创建 session（等同于 spawn）
        try:
            resp = http_post("/v1/sessions", {
                "message": task[:2000],
                "label": label,
                "runtime": "subagent",
            })
            session_key = resp.get("sessionKey") or resp.get("session_key") or ""
            if "error" in resp:
                session_key = f"error:{resp['error']}"
        except Exception as e:
            session_key = f"error:{e}"
        
        # 2. 等待 sub-agent 完成（轮询 history）
        result_text = ""
        if session_key and not session_key.startswith("error:"):
            time.sleep(5)  # 等待 agent 启动
            for _ in range(min(timeout // 5, 20)):
                time.sleep(5)
                try:
                    sk_enc = urllib.request.quote(session_key, safe="")
                    req = urllib.request.Request(
                        f"{GATEWAY_URL}/v1/sessions/{sk_enc}/history?limit=3",
                        headers={"Authorization": f"Bearer {TOKEN}"}
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        hist = json.loads(r.read())
                        for msg in reversed(hist.get("messages", [])):
                            if msg.get("role") == "assistant":
                                content = msg.get("content", "")
                                if isinstance(content, list):
                                    for c in content:
                                        if c.get("type") == "text":
                                            result_text = c["text"][:500]
                                            break
                                elif isinstance(content, str):
                                    result_text = content[:500]
                                break
                        if result_text:
                            break
                except Exception:
                    pass
        
        status = "success" if result_text else "partial"
        complete_spawn(
            spawn_id=spawn_id,
            child_session_key=session_key,
            result=result_text or f"session_key={session_key}",
            status=status,
        )
        
    except Exception as e:
        complete_spawn(
            spawn_id=spawn_id,
            status="error",
            error=f"_spawn_worker exception: {str(e)[:300]}",
        )


def check_spawn_results(spawn_ids: List[str] = None) -> Dict[str, Dict]:
    """
    检查 spawn 结果（非阻塞，只检查已存在的文件）。
    
    返回: {spawn_id: {"status": "...", "result": "...", "childSessionKey": "..."}}
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
                    "elapsed": time.time() - data.get("completed_at", time.time()),
                }
                if sid in _pending_spawns:
                    _pending_spawns[sid]["status"] = data.get("status", "done")
            except Exception:
                pass
    
    return results


def complete_spawn(spawn_id: str, child_session_key: str = None, result: str = None,
                  status: str = "success", error: str = None):
    """
    写入 spawn 结果到两个位置：
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


def get_pending_spawns() -> List[Dict]:
    """返回所有待处理的 spawn 请求"""
    pending = []
    for f in SPAWN_QUEUE_DIR.glob("*.json"):
        if f.name.startswith("_"):
            continue  # 跳过 worker 脚本
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


def wait_for_spawn(spawn_id: str, timeout: int = 120) -> Dict:
    """
    同步等待 spawn 完成（轮询结果文件）。
    成功返回结果 dict，超时返回 status=timeout 的 dict。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = read_spawn_result(spawn_id)
        if result:
            return result
        time.sleep(2)
    return {
        "spawn_id": spawn_id,
        "status": "timeout",
        "result": None,
        "error": f"waited {timeout}s for spawn result",
    }
