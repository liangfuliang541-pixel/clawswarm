"""
ClawSwarm - 节点龙虾客户端 v4
新增：Guard 隔离模块集成

用法: python swarm_node.py <node_id> [capability1] [capability2] ...
"""

import json, os, time, sys, shutil
import fnmatch
from datetime import datetime
from pathlib import Path

# 导入 Guard 安全模块
try:
    from guard import Guard, create_guard
    GUARD_AVAILABLE = True
except ImportError:
    GUARD_AVAILABLE = False

BASE_DIR       = r"D:\claw\swarm"

# 动态路径计算
def _dirs():
    """获取当前 BASE_DIR 对应的目录"""
    return {
        "queue": os.path.join(BASE_DIR, "queue"),
        "in_progress": os.path.join(BASE_DIR, "in_progress"),
        "results": os.path.join(BASE_DIR, "results"),
        "agents": os.path.join(BASE_DIR, "agents"),
        "logs": os.path.join(BASE_DIR, "logs"),
    }

QUEUE_DIR      = os.path.join(BASE_DIR, "queue")
IN_PROGRESS_DIR = os.path.join(BASE_DIR, "in_progress")
RESULTS_DIR    = os.path.join(BASE_DIR, "results")
AGENTS_DIR     = os.path.join(BASE_DIR, "agents")
MAX_RUNTIME_SEC = 300  # 默认每个节点最多跑5分钟

# 初始化目录
def _init_dirs():
    dirs = _dirs()
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)

_init_dirs()

# ── 隔离与审计配置 ─────────────────────────────────────────────────────────

# 禁止访问的路径模式（防止目录穿越）
FORBIDDEN_PATH_PATTERNS = [
    r"..",
    r"~\.ssh",
    r"~\.aws",
    r"C:\Windows",
    r"C:\Program Files",
    r"/etc/passwd",
]

# 审计日志
AUDIT_LOG_FILE = os.path.join(BASE_DIR, "audit.log")

def audit_log(node_id: str, task_id: str, event: str, details: dict = None):
    """记录审计日志"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "node_id": node_id,
        "task_id": task_id,
        "event": event,
        "details": details or {}
    }
    try:
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 审计失败不应中断任务

def validate_path_access(path: str, allowed_root: str) -> bool:
    """验证路径是否在允许的根目录内"""
    try:
        abs_path = os.path.abspath(path)
        abs_root = os.path.abspath(allowed_root)
        
        # 检查禁止模式
        for pattern in FORBIDDEN_PATH_PATTERNS:
            if fnmatch.fnmatch(abs_path.lower(), pattern.lower()):
                return False
        
        # 检查是否在允许目录下
        return abs_path.startswith(abs_root)
    except Exception:
        return False

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def write_json(path, data):
    # 原子写入：先写.tmp再rename，防止并发损坏
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)          # Windows原子操作

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ── 节点心跳 ─────────────────────────────────────────────────────────────────

def write_heartbeat(node_id, capabilities, status="idle", current_task_id=None):
    """写入心跳文件，主龙虾据此判断节点存活性"""
    dirs = _dirs()
    write_json(os.path.join(dirs["agents"], f"{node_id}.json"), {
        "node_id":          node_id,
        "capabilities":     capabilities,
        "status":           status,
        "current_task_id":  current_task_id,
        "last_heartbeat":   datetime.now().isoformat(),
    })

# ── 任务抢占 ─────────────────────────────────────────────────────────────────

def poll_task(node_id):
    """
    从 queue/ 抢占一个 pending 任务。

    流程：
    1. 扫描 queue/ 下所有 .json
    2. 找到 status=pending 的任务
    3. 原子 rename 到 in_progress/（防止多节点抢同一个任务）
    4. 写回 status=running + runner=node_id
    5. 返回任务对象
    """
    dirs = _dirs()
    queue_dir = dirs["queue"]
    in_progress_dir = dirs["in_progress"]
    
    for fname in sorted(os.listdir(queue_dir)):
        if not fname.endswith(".json"):
            continue
        src = os.path.join(queue_dir, fname)
        dst = os.path.join(in_progress_dir, fname)

        try:
            # 尝试原子rename（抢占锁）
            os.replace(src, dst)
        except FileNotFoundError:
            # 已被其他节点抢走，跳过
            continue

        # rename成功，当前节点获得任务
        try:
            task = read_json(dst)
            task["status"]      = "running"
            task["runner"]      = node_id
            task["started_at"] = datetime.now().isoformat()
            write_json(dst, task)
            log(f"[POLL] Got task {task['id']}")
            return task
        except Exception as e:
            # 文件损坏，归还到queue
            try:
                os.replace(dst, src)
            except Exception:
                pass
            log(f"[ERR] Failed to read polled task: {e}")
            continue

    return None  # 无任务

# ── 任务完成 ─────────────────────────────────────────────────────────────────

def complete_task(task_id, result, node_id):
    """
    任务成功完成：
    1. in_progress/ 里的任务文件 -> results/（带结果）
    2. 同时在 results/ 写入独立结果文件
    """
    dirs = _dirs()
    src = os.path.join(dirs["in_progress"], f"{task_id}.json")
    dst = os.path.join(dirs["results"], f"{task_id}.json")

    # 1. 独立结果文件（仅此一份）
    result_file = os.path.join(dirs["results"], f"r_{task_id}.json")
    write_json(result_file, {
        "task_id":     task_id,
        "result":      result,
        "completed_at": datetime.now().isoformat(),
        "node":        node_id,
        "status":      "done"
    })

    # 2. 删除 in_progress 中的文件
    try:
        os.remove(src)
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"[ERR] cleanup in_progress failed: {e}")

    # 审计日志
    audit_log(node_id, task_id, "task_complete", {"result": str(result)[:200]})
    log(f"[DONE] {task_id}")

# ── 任务失败 ─────────────────────────────────────────────────────────────────

def fail_task(task_id, error, node_id):
    """
    任务失败：
    1. 读 in_progress/ 里的文件
    2. 标记失败原因
    3. 移到 results/（不再放回queue，避免死循环）
    """
    dirs = _dirs()
    src = os.path.join(dirs["in_progress"], f"{task_id}.json")
    dst = os.path.join(dirs["results"], f"{task_id}.json")

    # 1. 独立结果文件
    result_file = os.path.join(dirs["results"], f"r_{task_id}.json")
    write_json(result_file, {
        "task_id":    task_id,
        "error":      str(error),
        "failed_at":  datetime.now().isoformat(),
        "node":       node_id,
        "status":     "failed"
    })

    # 2. 删除 in_progress 中的文件
    try:
        os.remove(src)
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"[ERR] cleanup in_progress failed: {e}")

    # 审计日志
    audit_log(node_id, task_id, "task_fail", {"error": str(error)})
    log(f"[FAIL] {task_id}: {error}")

# ── 任务执行核心 ─────────────────────────────────────────────────────────────

def execute_task(task, node_id):
    """
    任务执行入口。替换这里接入实际的 agent 能力。
    目前是占位逻辑。
    """
    task_id = task.get("id", "unknown")
    task_type = task.get("type", "general")
    desc = task.get("description", task.get("prompt", ""))

    # 审计：任务开始执行
    audit_log(node_id, task_id, "task_start", {
        "type": task_type,
        "description": desc[:100]
    })

    # TODO: 接入 sessions_spawn / web_fetch / exec 等真实能力
    result = f"[OK] Task [{task_id}] executed: {desc[:80]}"
    
    # 审计：任务执行完成（简单模式）
    audit_log(node_id, task_id, "task_exec_ok", {"result": result[:100]})
    return result

# ── 主循环 ───────────────────────────────────────────────────────────────────

def run_node(node_id, capabilities, poll_interval=5, max_runtime=None):
    start_time = time.time()
    task_count = 0

    # 注册节点
    write_heartbeat(node_id, capabilities, status="online")
    log(f"[BOOT] Node [{node_id}] online, capabilities={capabilities}")

    while True:
        # 超时退出
        if max_runtime and (time.time() - start_time) > max_runtime:
            log(f"[STOP] Max runtime ({max_runtime}s) reached")
            break

        # 发送心跳
        write_heartbeat(node_id, capabilities, status="idle")

        # 抢占任务
        task = poll_task(node_id)

        if task:
            # 更新心跳为忙碌状态
            write_heartbeat(node_id, capabilities,
                           status="busy",
                           current_task_id=task["id"])

            task_count += 1
            log(f"[WORK] [{task['id']}]: {task.get('description','')[:60]}")

            try:
                result = execute_task(task, node_id)
                complete_task(task["id"], result, node_id)
            except Exception as e:
                fail_task(task["id"], str(e), node_id)
        else:
            # 无任务时降低日志频率（每12轮打一次）
            if task_count == 0 or task_count % 12 == 0:
                log(f"[IDLE] [{node_id}] waiting... (completed={task_count})")

        time.sleep(poll_interval)

# ── 入口 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python swarm_node.py <node_id> [capability1] ...]")
        sys.exit(1)

    node_id      = sys.argv[1]
    capabilities = sys.argv[2:] if len(sys.argv) > 2 else ["general"]

    # ── 初始化 Guard 安全模块 ─────────────────────────────────────────────
    guard = None
    if GUARD_AVAILABLE:
        try:
            guard = create_guard(BASE_DIR, node_id)
            guard.audit("node_start", {"capabilities": capabilities})
            print(f"[Guard] 安全隔离已启用 - 工作目录: {guard.workspace}")
        except Exception as e:
            print(f"[Guard] 初始化失败: {e}")

    # 解析 max_runtime 环境变量（用于测试时限制运行时长）
    max_runtime = int(os.environ.get("SWARM_MAX_RUNTIME", 0)) or None

    try:
        run_node(node_id, capabilities, poll_interval=5, max_runtime=max_runtime)
    except KeyboardInterrupt:
        log(f"[EXIT] Node [{node_id}] stopped by user")
