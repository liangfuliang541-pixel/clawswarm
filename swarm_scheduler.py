"""
ClawSwarm - 主龙虾调度器 v2
职责：
  1. 接收任务 → 写入 queue/
  2. 监控节点心跳 → 判断存活性
  3. 回收超时任务 → 放回 queue/ 重试
  4. 聚合结果 → 汇总多个任务的结果

用法:
  python swarm_scheduler.py add <prompt> [--type TYPE] [--priority N]
  python swarm_scheduler.py status
  python swarm_scheduler.py results [task_id]
  python swarm_scheduler.py cleanup    # 清理超时任务
  python swarm_scheduler.py watch      # 持续监控模式
"""

import json, os, sys, time, uuid
from datetime import datetime, timezone

from paths import (
    BASE_DIR, QUEUE_DIR, IN_PROGRESS_DIR, RESULTS_DIR,
    AGENTS_DIR, LOGS_DIR, can_node_handle, find_best_node,
)

# ── 配置 ─────────────────────────────────────────────────────────────────────
STALE_THRESHOLD_SEC = 120   # 心跳超过这个秒数判定为stale
OFFLINE_THRESHOLD_SEC = 300  # 心跳超过这个秒数判定为offline
TASK_TIMEOUT_SEC   = 300    # 任务执行超时（放回queue重新分配）

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg):
    print(f"[{ts()}] {msg}", flush=True)

# ── 任务管理 ─────────────────────────────────────────────────────────────────

def create_task(prompt, task_type="general", priority=1, metadata=None, task_id=None):
    """创建一个新任务并加入队列，自动匹配合适节点"""
    if task_id is None:
        task_id = f"t_{uuid.uuid4().hex[:12]}"

    # ── spawn 类型任务不通过调度器，直接写队列让 orchestrator 处理 ──────────
    if task_type == "spawn":
        task = {
            "id":           task_id,
            "type":         task_type,
            "description":  prompt,
            "prompt":       prompt,
            "priority":     priority,
            "status":       "pending",
            "assigned_to":  None,          # orchestrator 通过 spawn_manager 处理
            "created_at":   datetime.now().isoformat(),
            "retry_count":  0,
            "max_retries":  3,
            "timeout_seconds": TASK_TIMEOUT_SEC,
            "metadata":     metadata or {}
        }
        write_json(os.path.join(QUEUE_DIR, f"{task_id}.json"), task)
        log(f"[SCHED] {task_id} (spawn) -> queue (orchestrator handles)")
        return task_id, task

    # 能力感知调度：自动选择最佳节点（本地+远程）
    online = get_online_nodes(STALE_THRESHOLD_SEC)
    best = find_best_node(task_type, online)

    # 如果选中了远程节点，走远程调度路径
    if best and best.get("is_remote"):
        return create_task_for_remote_node(task_id, prompt, task_type, priority, best, metadata)

    task = {
        "id":           task_id,
        "type":         task_type,
        "description":  prompt,
        "prompt":       prompt,
        "priority":     priority,
        "status":       "pending",
        "assigned_to":  best["node_id"] if best else None,
        "created_at":   datetime.now().isoformat(),
        "retry_count":  0,
        "max_retries":  3,
        "timeout_seconds": TASK_TIMEOUT_SEC,
        "metadata":     metadata or {}
    }
    write_json(os.path.join(QUEUE_DIR, f"{task_id}.json"), task)

    if best:
        log(f"[SCHED] {task_id} ({task_type}) -> {best['node_id']} "
            f"caps={best.get('capabilities', [])}")
    else:
        log(f"[SCHED] {task_id} ({task_type}) -> unassigned (no capable node online)")

    return task_id, task


def create_task_for_remote_node(
    task_id: str,
    prompt: str,
    task_type: str = "general",
    priority: int = 1,
    remote_node: dict = None,
    metadata: dict = None,
):
    """
    创建任务并调度到远程节点（通过 relay 执行，后台线程异步）。
    任务完成后写入 results/r_{task_id}.json，orchestrator 的 ResultWatcher 会读取。
    """
    if remote_node is None:
        return task_id, {"id": task_id, "error": "no remote node specified"}

    node_id = remote_node["node_id"]
    relay_url = remote_node.get("relay_url", "")

    task = {
        "id":          task_id,
        "type":        task_type,
        "description": prompt,
        "prompt":      prompt,
        "priority":    priority,
        "status":      "pending",
        "assigned_to": node_id,
        "assigned_to_relay": relay_url,
        "created_at":  datetime.now().isoformat(),
        "retry_count": 0,
        "max_retries": 3,
        "timeout_seconds": TASK_TIMEOUT_SEC,
        "metadata":    metadata or {},
        "node_type":   "remote",
    }

    log(f"[SCHED] {task_id} ({task_type}) -> remote:{node_id} via relay")

    # 后台线程：发送到远程 relay 并异步执行
    try:
        from relay_client import RemoteNode, exec_task_async_via_relay
        node = RemoteNode(
            node_id=node_id,
            relay_url=relay_url,
            name=remote_node.get("name"),
            capabilities=remote_node.get("capabilities"),
        )
        # 异步执行，不阻塞调度器
        exec_task_async_via_relay(task_id, prompt, node, timeout=TASK_TIMEOUT_SEC)
    except Exception as e:
        log(f"[SCHED] Remote exec failed for {task_id}: {e}")
        task["status"] = "error"
        task["error"] = str(e)

    return task_id, task

def get_all_tasks():
    """获取所有任务（按目录分组）"""
    all_tasks = []
    for d, dir_filter in [
        (QUEUE_DIR,       "pending"),
        (IN_PROGRESS_DIR, "running"),
    ]:
        if not os.path.exists(d):
            continue
        for fname in os.listdir(d):
            if not fname.endswith(".json"):
                continue
            try:
                task = read_json(os.path.join(d, fname))
                all_tasks.append(task)
            except Exception:
                pass

    # results里的也加入
    if os.path.exists(RESULTS_DIR):
        for fname in os.listdir(RESULTS_DIR):
            if not fname.endswith(".json") or fname.startswith("r_"):
                continue
            try:
                task = read_json(os.path.join(RESULTS_DIR, fname))
                all_tasks.append(task)
            except Exception:
                pass

    return all_tasks

def get_task_result(task_id):
    """获取任务结果"""
    for prefix in ["", "r_"]:
        rpath = os.path.join(RESULTS_DIR, f"{prefix}{task_id}.json")
        if os.path.exists(rpath):
            return read_json(rpath)
    return None

# ── 节点管理 ─────────────────────────────────────────────────────────────────

def get_online_nodes(threshold_sec=STALE_THRESHOLD_SEC):
    """获取当前在线的节点列表（本地 + 远程）"""
    now = datetime.now()
    online = []

    # ── 本地节点 ──────────────────────────────────────────────────────────
    if os.path.exists(AGENTS_DIR):
        for fname in os.listdir(AGENTS_DIR):
            if not fname.endswith(".json"):
                continue
            try:
                agent = read_json(os.path.join(AGENTS_DIR, fname))
                last_seen = datetime.fromisoformat(agent["last_heartbeat"])
                age = (now - last_seen).total_seconds()
                agent["heartbeat_age_sec"] = int(age)
                if age < threshold_sec:
                    online.append(agent)
            except Exception:
                pass

    # ── 远程节点（通过 relay 连通性判断）────────────────────────────────────
    try:
        from relay_client import RemoteNodeManager
        mgr = RemoteNodeManager()
        for node_info in mgr.list_nodes():
            if node_info.get("relay_reachable"):
                # 远程节点没有本地 heartbeat，用注册时间判断
                online.append({
                    "node_id": node_info["node_id"],
                    "name": node_info.get("name", node_info["node_id"]),
                    "type": "remote",
                    "capabilities": node_info.get("capabilities", []),
                    "relay_url": node_info.get("relay_url", ""),
                    "heartbeat_age_sec": 0,
                    "is_remote": True,
                })
    except ImportError:
        pass  # relay_client 不可用，跳过远程节点

    return online

# ── 健康监测：回收超时任务 ──────────────────────────────────────────────────────

def recover_stale_tasks():
    """
    扫描 in_progress/ 目录，回收超时任务。
    逻辑：
      - 任务在 in_progress/ 但 runner 心跳已消失 → 放回 queue
      - 任务在 in_progress/ 超过 TASK_TIMEOUT_SEC → 放回 queue
      - 超过 max_retries → 移到 results/ 标记 failed
    """
    recovered = []
    if not os.path.exists(IN_PROGRESS_DIR):
        return recovered

    now = datetime.now()
    online_nodes = {n["node_id"] for n in get_online_nodes(OFFLINE_THRESHOLD_SEC)}

    for fname in os.listdir(IN_PROGRESS_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(IN_PROGRESS_DIR, fname)
        try:
            task = read_json(fpath)
        except Exception:
            continue

        task_id    = task.get("id") or task.get("task_id", "")
        task_type_val = task.get("type") or task.get("task_type", "")
        # 孤儿任务（无 id 且无 prompt）→ orchestrator 自己管理，直接标记失败
        if not task_id and not task.get("prompt"):
            dst = os.path.join(RESULTS_DIR, fname)
            task["status"]    = "failed"
            task["error"]    = "Orphan task (no id/prompt)"
            task["failed_at"] = datetime.now().isoformat()
            write_json(dst, task)
            os.remove(fpath)
            log(f"[RECOVER] {fname} -> FAILED (orphan orchestrator task)")
            recovered.append(fname)
            continue

        if not task_id:
            continue
        runner     = task.get("runner", "unknown")
        started_at = task.get("started_at", task.get("created_at", ""))
        retry      = task.get("retry_count", 0)
        max_ret   = task.get("max_retries", 3)

        # 计算已运行时间
        try:
            start = datetime.fromisoformat(started_at)
            age_sec = (now - start).total_seconds()
        except Exception:
            age_sec = 0

        # 判断是否需要回收
        should_recover = False
        reason = ""

        if runner not in online_nodes:
            should_recover = True
            reason = f"node_offline (runner={runner})"
        elif age_sec > TASK_TIMEOUT_SEC:
            should_recover = True
            reason = f"timeout ({int(age_sec)}s > {TASK_TIMEOUT_SEC}s)"

        if not should_recover:
            continue

        # spawn 类型任务不重试，直接标记失败（由 orchestrator 处理）
        task_type_val = task.get("type") or task.get("task_type", "")
        if task_type_val == "spawn" or "spawn" in task_id.lower():
            dst = os.path.join(RESULTS_DIR, fname)
            task["status"] = "failed"
            task["error"] = f"Spawn task timed out: {reason}"
            task["failed_at"] = datetime.now().isoformat()
            write_json(dst, task)
            os.remove(fpath)
            log(f"[RECOVER] {task_id} -> FAILED (spawn task, orchestrator handles)")
            recovered.append(task_id)
            continue

        if retry + 1 >= max_ret:
            # 达到最大重试，标记失败
            dst = os.path.join(RESULTS_DIR, fname)
            task["status"]   = "failed"
            task["error"]    = f"Max retries exceeded: {reason}"
            task["failed_at"] = datetime.now().isoformat()
            write_json(dst, task)
            os.remove(fpath)
            log(f"[RECOVER] {task_id} -> FAILED (max retries): {reason}")
        else:
            # 放回队列重试
            dst = os.path.join(QUEUE_DIR, fname)
            task["status"]      = "pending"
            task["retry_count"] = retry + 1
            task["runner"]      = None
            task["started_at"]  = None
            task["last_recover"] = datetime.now().isoformat()
            task["recover_reason"] = reason
            write_json(dst, task)
            os.remove(fpath)
            log(f"[RECOVER] {task_id} -> requeued ({reason}), retry={retry+1}/{max_ret}")

        recovered.append(task_id)

    return recovered

# ── 状态展示 ─────────────────────────────────────────────────────────────────

def show_status():
    """展示系统整体状态"""
    tasks     = get_all_tasks()
    pending   = [t for t in tasks if t.get("status") == "pending"]
    running   = [t for t in tasks if t.get("status") == "running"]
    done      = [t for t in tasks if t.get("status") == "done"]
    failed    = [t for t in tasks if t.get("status") == "failed"]
    nodes     = get_online_nodes()

    print()
    print("=" * 55)
    print(f"  ClawSwarm Status  [{ts()}]")
    print("=" * 55)
    print(f"  Nodes Online : {len(nodes)}")
    for n in nodes:
        print(f"    - {n['node_id']} [{n.get('status','?')}] "
              f"HB={n.get('heartbeat_age_sec',0)}s caps={n.get('capabilities',[])}")
    print(f"  Tasks:")
    print(f"    Pending  : {len(pending)}")
    print(f"    Running  : {len(running)}")
    print(f"    Done     : {len(done)}")
    print(f"    Failed   : {len(failed)}")
    print("=" * 55)

    if running:
        print("  Running tasks:")
        for t in running:
            age = ""
            if t.get("started_at"):
                try:
                    s = datetime.fromisoformat(t["started_at"])
                    age = f" ({int((datetime.now()-s).total_seconds())}s)"
                except Exception:
                    pass
            print(f"    [{t.get('id') or t.get('task_id','?')}] runner={t.get('runner','?')} {t.get('description','')[:40]}{age}")
    print()

# ── 命令行入口 ────────────────────────────────────────────────────────────────

def cmd_add(args_list):
    task_id, task = create_task(
        prompt=args_list[0] if args_list else "No prompt provided",
        task_type=args.task_type or "general",
        priority=args.priority or 1
    )
    log(f"[ADD] Created task {task_id}: {task['description'][:60]}")
    print(f"Task {task_id} added to queue.")

def cmd_status(args):
    show_status()

def cmd_results(args):
    if args.task_id:
        r = get_task_result(args.task_id)
        if r:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print(f"No result for {args.task_id}")
    else:
        # 列出所有结果
        if not os.path.exists(RESULTS_DIR):
            print("No results yet.")
            return
        for fname in sorted(os.listdir(RESULTS_DIR)):
            if not fname.endswith(".json"):
                continue
            r = read_json(os.path.join(RESULTS_DIR, fname))
            print(f"  {fname}: status={r.get('status','?')} "
                  f"node={r.get('node','?')} "
                  f"desc={r.get('description', r.get('result',''))[:50]}")

def cmd_cleanup(args):
    log("[CLEANUP] Scanning for stale tasks...")
    recovered = recover_stale_tasks()
    log(f"[CLEANUP] Done. Recovered {len(recovered)} tasks.")
    for tid in recovered:
        print(f"  - {tid}")

def cmd_watch(args):
    log("[WATCH] Starting monitor mode (Ctrl+C to stop)...")
    try:
        while True:
            recover_stale_tasks()
            show_status()
            time.sleep(10)
    except KeyboardInterrupt:
        log("[WATCH] Stopped.")

# ── Scheduler 类封装 ───────────────────────────────────────────────────

class Scheduler:
    """
    调度器类封装（支持自定义 base_dir）
    
    用法:
        scheduler = Scheduler(base_dir="D:\\claw\\swarm")
        scheduler.add_task({"prompt": "分析这个"})
        status = scheduler.get_status()
    """
    
    def __init__(self, base_dir: str = None, poll_interval: int = 5):
        self.base_dir = base_dir or BASE_DIR
        self._queue = os.path.join(self.base_dir, "queue")
        self._in_progress = os.path.join(self.base_dir, "in_progress")
        self._results = os.path.join(self.base_dir, "results")
        self._agents = os.path.join(self.base_dir, "agents")
        self._logs = os.path.join(self.base_dir, "logs")
        self.poll_interval = poll_interval

        for d in [self._queue, self._in_progress, self._results, self._agents, self._logs]:
            os.makedirs(d, exist_ok=True)
    
    def add_task(self, task: dict) -> str:
        """添加任务"""
        return create_task(
            prompt=task.get("prompt", ""),
            task_type=task.get("type", "general"),
            priority=task.get("priority", 1),
            metadata=task.get("metadata")
        )
    
    def get_status(self) -> dict:
        """获取状态"""
        return show_status()
    
    def get_task_result(self, task_id: str) -> dict:
        """获取任务结果"""
        return get_task_result(task_id)
    
    def recover_stale(self):
        """恢复超时任务"""
        return recover_stale_tasks()
    
    def cleanup(self):
        """清理超时任务"""
        return cmd_cleanup(Args())


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("Commands: add | status | results | cleanup | watch")
        sys.exit(1)

    cmd = sys.argv[1]

    # 简单参数解析（避免 shadowing built-in 'type'）
    class Args:
        def __init__(self):
            self._args = sys.argv[2:]

        def _get_task_id(self):
            return self._args[1] if len(self._args) > 1 else None

        def _get_type(self):
            for i, a in enumerate(self._args):
                if a == "--type" and i+1 < len(self._args):
                    return self._args[i+1]
            return None

        def _get_priority(self):
            for i, a in enumerate(self._args):
                if a == "--priority" and i+1 < len(self._args):
                    return int(self._args[i+1])
            return None

        @property
        def task_id(self):   return self._get_task_id()
        @property
        def priority(self):  return self._get_priority()
        # 'type' is a Python built-in; expose as 'task_type' to avoid shadowing
        @property
        def task_type(self): return self._get_type()

    args = Args()
    if cmd == "add":
        cmd_add(args._args)
    elif cmd == "status":
        cmd_status(args)
    elif cmd == "results":
        cmd_results(args)
    elif cmd == "cleanup":
        cmd_cleanup(args)
    elif cmd == "watch":
        cmd_watch(args)
    else:
        print(f"Unknown command: {cmd}")
        print("Commands: add | status | results | cleanup | watch")
