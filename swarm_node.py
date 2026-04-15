"""
ClawSwarm - 节点龙虾客户端 v5
新增：watchdog push 模式（有任务立刻执行）+ executor 真实执行

用法: python swarm_node.py <node_id> [capability1] [capability2] ...
"""

import json, os, time, sys, shutil, asyncio
import fnmatch
import threading
from datetime import datetime
from pathlib import Path

from paths import (
    BASE_DIR, QUEUE_DIR, IN_PROGRESS_DIR, RESULTS_DIR,
    AGENTS_DIR, LOGS_DIR, AUDIT_LOG_FILE, can_node_handle,
)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

MAX_RUNTIME_SEC = 300  # 默认每个节点最多跑5分钟

# ── Guard 安全模块（延迟导入）────────────────────────────────────────────

_GUARD_AVAILABLE = None

def _get_guard():
    global _GUARD_AVAILABLE
    if _GUARD_AVAILABLE is None:
        try:
            from guard import create_guard
            _GUARD_AVAILABLE = create_guard
        except ImportError:
            _GUARD_AVAILABLE = False
    return _GUARD_AVAILABLE


# ── Watchdog Push 模式 ───────────────────────────────────────────────────────

class QueueFileHandler(FileSystemEventHandler if HAS_WATCHDOG else object):
    """
    监听 queue/ 目录，新任务文件出现时立刻触发 poll。
    配合主循环的 threading.Event 实现 push 通知。
    """

    def __init__(self, node_id, capabilities):
        self.node_id = node_id
        self.capabilities = capabilities
        self.trigger = threading.Event()

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".json"):
            # 通知主循环有新任务
            self.trigger.set()

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".json"):
            self.trigger.set()

    def reset(self):
        self.trigger.clear()


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
    write_json(os.path.join(AGENTS_DIR, f"{node_id}.json"), {
        "node_id":          node_id,
        "capabilities":     list(capabilities),
        "status":           status,
        "current_task_id":  current_task_id,
        "last_heartbeat":   datetime.now().isoformat(),
    })

# ── 任务抢占 ─────────────────────────────────────────────────────────────────

def poll_task(node_id, capabilities=None):
    """
    从 queue/ 抢占一个 pending 任务。

    能力过滤规则：
      1. 任务已分配给当前节点 → 直接抢
      2. 任务未分配 + 节点有对应能力 → 先占住再抢
      3. general 任务未分配 → 任意节点可抢
      4. 其他 → 跳过

    流程：
    1. 扫描 queue/ 下所有 .json
    2. 能力匹配过滤
    3. 原子 rename 到 in_progress/（防止多节点抢同一个任务）
    4. 写回 status=running + runner=node_id
    5. 返回任务对象
    """
    if capabilities is None:
        capabilities = ["general"]

    for fname in sorted(os.listdir(QUEUE_DIR)):
        if not fname.endswith(".json"):
            continue
        src = os.path.join(QUEUE_DIR, fname)
        dst = os.path.join(IN_PROGRESS_DIR, fname)

        # 预读任务元数据（不做 rename），判断能力匹配
        try:
            task_meta = read_json(src)
        except Exception:
            continue

        assigned_to = task_meta.get("assigned_to")
        task_type = task_meta.get("type", "general")

        # 规则1：任务已分配给当前节点
        if assigned_to is not None and assigned_to != node_id:
            continue  # 分配给别人了，跳过

        # 规则2：任务未分配，检查能力
        if assigned_to is None and not can_node_handle(task_type, capabilities):
            continue  # 没能力处理，跳过

        # 尝试原子 rename（抢占锁）
        try:
            os.replace(src, dst)
        except FileNotFoundError:
            continue  # 已被其他节点抢走

        # rename 成功，当前节点获得任务
        try:
            task = read_json(dst)
            task["status"]      = "running"
            task["runner"]      = node_id
            task["started_at"] = datetime.now().isoformat()
            write_json(dst, task)
            log(f"[POLL] Got task {task['id']} (type={task_type})")
            return task
        except Exception as e:
            # 文件损坏，归还到 queue
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
    1. in_progress/ 里的任务文件删除
    2. 在 results/ 写入结果文件
    """
    src = os.path.join(IN_PROGRESS_DIR, f"{task_id}.json")

    # 独立结果文件（仅此一份）
    result_file = os.path.join(RESULTS_DIR, f"r_{task_id}.json")
    write_json(result_file, {
        "task_id":     task_id,
        "result":      result,
        "completed_at": datetime.now().isoformat(),
        "node":        node_id,
        "status":      "done"
    })

    # 删除 in_progress 中的文件
    try:
        os.remove(src)
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"[ERR] cleanup in_progress failed: {e}")

    log(f"[DONE] {task_id}")

# ── 任务失败 ─────────────────────────────────────────────────────────────────

def fail_task(task_id, error, node_id):
    """
    任务失败：
    1. 删除 in_progress/ 里的文件
    2. 在 results/ 写入失败记录
    """
    src = os.path.join(IN_PROGRESS_DIR, f"{task_id}.json")

    # 结果文件
    result_file = os.path.join(RESULTS_DIR, f"r_{task_id}.json")
    write_json(result_file, {
        "task_id":    task_id,
        "error":      str(error),
        "failed_at":  datetime.now().isoformat(),
        "node":       node_id,
        "status":     "failed"
    })

    # 删除 in_progress 中的文件
    try:
        os.remove(src)
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"[ERR] cleanup in_progress failed: {e}")

    log(f"[FAIL] {task_id}: {error}")

# ── 任务执行核心 ─────────────────────────────────────────────────────────────

def execute_task(task, node_id):
    """
    任务执行入口。

    根据 task.type / task.mode 分发到不同的执行逻辑：
    - research/fetch/analyze → 通过 executor 模块处理
    - code/exec/python      → 通过 executor 模块处理
    - general/其他          → 占位返回（等待接入 sessions_spawn）
    """
    task_id = task.get("id", "unknown")
    task_type = task.get("type", "general")
    task_mode = task.get("mode", "spawn")
    desc = task.get("description", task.get("prompt", ""))

    log(f"[EXEC] {task_id} type={task_type} mode={task_mode}: {desc[:60]}")

    # 尝试使用 executor 模块执行
    try:
        from executor import TaskExecutor

        executor = TaskExecutor(default_timeout=task.get("timeout_seconds", 300))

        # 映射 task.type → executor mode
        mode_map = {
            "research": "spawn",
            "fetch":    "fetch",
            "code":     "python",
            "write":    "spawn",
            "read":     "exec",
            "analyze":  "spawn",
            "report":   "spawn",
        }
        exec_mode = mode_map.get(task_type, task_mode or "spawn")

        # 从 task 对象提取执行参数（优先 metadata，fallback 到 task 顶层字段）
        meta = task.get("metadata", {}) or {}
        prompt = task.get("prompt", task.get("description", ""))

        exec_task = {
            "id":       task_id,
            "mode":     exec_mode,
            "prompt":   prompt,
            "type":     task_type,
            "node_id":  node_id,
            "url":      meta.get("url") or (prompt if exec_mode == "fetch" else None),
            "command":  meta.get("command") or task.get("command"),
            "code":     meta.get("code") or task.get("code"),
            "timeout":  task.get("timeout_seconds", 300),
        }

        # executor 是 async 的，需要跑 event loop
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(executor.execute(exec_task))
            output = result.output if result.output is not None else f"[OK] {desc[:80]}"
        finally:
            loop.close()

        return output

    except ImportError:
        # executor 不可用，降级为占位执行
        log(f"[WARN] executor module not available, using placeholder")
        return f"[OK] Task [{task_id}] executed (placeholder): {desc[:80]}"
    except Exception as e:
        raise RuntimeError(f"execute_task failed: {e}") from e

# ── 主循环 ───────────────────────────────────────────────────────────────────

def run_node(node_id, capabilities, poll_interval=5, max_runtime=None):
    start_time = time.time()
    task_count = 0

    # 注册节点
    write_heartbeat(node_id, capabilities, status="online")
    log(f"[BOOT] Node [{node_id}] online, capabilities={capabilities}")

    # ── Push 模式：watchdog 监听队列目录 ────────────────────────────────
    observer = None
    file_handler = None
    poll_func = lambda: poll_task(node_id, capabilities)

    if HAS_WATCHDOG:
        try:
            file_handler = QueueFileHandler(node_id, capabilities)
            observer = Observer()
            observer.schedule(file_handler, QUEUE_DIR, recursive=False)
            observer.daemon = True
            observer.start()
            log(f"[PUSH] Watchdog active on {QUEUE_DIR} — instant task pickup")
        except Exception as e:
            log(f"[WARN] Watchdog failed ({e}), falling back to polling")

    # ── 主循环 ──────────────────────────────────────────────────────────
    poll_counter = 0

    while True:
        # 超时退出
        if max_runtime and (time.time() - start_time) > max_runtime:
            log(f"[STOP] Max runtime ({max_runtime}s) reached")
            break

        # 发送心跳
        write_heartbeat(node_id, capabilities,
                        status="idle" if task_count == 0 or task_count % 4 else "busy",
                        current_task_id=None)

        # ── 任务抢占 ──────────────────────────────────────────────────
        task = poll_func()

        if task:
            # 更新心跳为忙碌
            write_heartbeat(node_id, capabilities,
                           status="busy",
                           current_task_id=task["id"])

            task_count += 1
            log(f"[WORK] [{task['id']}]: {task.get('description', '')[:60]}")

            try:
                result = execute_task(task, node_id)
                complete_task(task["id"], result, node_id)
            except Exception as e:
                fail_task(task["id"], str(e), node_id)

            # 重置 watchdog trigger（如果使用了 push 模式）
            if file_handler:
                file_handler.reset()

        else:
            # 无任务：进入等待
            if HAS_WATCHDOG and file_handler:
                # Push 模式：最多等 poll_interval 秒，或等 watchdog 通知
                # 等待时每 500ms 检查一次是否超时
                waited = 0
                while waited < poll_interval:
                    # wait(timeout) 返回 True 表示被触发，False 表示超时
                    triggered = file_handler.trigger.wait(timeout=0.5)
                    if triggered:
                        file_handler.reset()
                        break  # 被触发，立刻去 poll
                    waited += 0.5
            else:
                # Fallback：纯轮询
                time.sleep(poll_interval)
                poll_counter += 1
                if poll_counter % 24 == 0:  # 每约2分钟打一次
                    log(f"[IDLE] [{node_id}] waiting... (completed={task_count})")

    # ── 清理 ──────────────────────────────────────────────────────────────
    if observer:
        observer.stop()
        observer.join(timeout=3)
    log(f"[EXIT] Node [{node_id}] stopped — completed={task_count} tasks")

# ── 入口 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python swarm_node.py <node_id> [capability1] ...]")
        sys.exit(1)

    node_id      = sys.argv[1]
    capabilities = sys.argv[2:] if len(sys.argv) > 2 else ["general"]

    # ── 初始化 Guard 安全模块 ─────────────────────────────────────────────
    guard = None
    guard_factory = _get_guard()
    if guard_factory and guard_factory is not False:
        try:
            guard = guard_factory(BASE_DIR, node_id)
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
