"""
ClawSwarm - 节点 HTTP API 服务

每个节点运行一个轻量 HTTP 服务，供主龙虾（Master）主动推送任务。

启动：
    python node_api.py claw_alpha search write code
    python node_api.py claw_beta  read write
    python node_api.py claw_gamma search analyze report

API 端点：
    GET  /status        — 节点状态（ID / 能力 / 运行中任务）
    GET  /health        — 健康检查
    POST /poll           — 节点主动拉取任务（能力匹配）
    POST /complete       — 提交任务结果
    GET  /tasks          — 列出当前节点的任务
    POST /shutdown        — 优雅关闭

主龙虾调用示例：
    POST http://localhost:5171/poll  {"node_id": "claw_alpha"}
    POST http://localhost:5171/complete {"task_id": "t_xxx", "result": {...}}
"""

import os, sys, json, time, uuid, asyncio, threading, signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from typing import Dict, Optional

# ── 路径 ─────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import (
    BASE_DIR, QUEUE_DIR, IN_PROGRESS_DIR, RESULTS_DIR, AGENTS_DIR,
    LOGS_DIR, ensure_dirs, can_node_handle,
)
from models import TaskStatus

# ── 节点状态 ─────────────────────────────────────────────────────────────

class NodeState:
    """节点运行时状态"""

    def __init__(self, node_id: str, capabilities: list, port: int):
        self.node_id = node_id
        self.capabilities = capabilities or []
        self.port = port
        self.status = "idle"       # idle / busy / offline
        self.current_task_id: Optional[str] = None
        self.current_task_start: Optional[float] = None
        self.started_at = datetime.now().isoformat()
        self._lock = threading.RLock()

    def busy(self, task_id: str):
        with self._lock:
            self.status = "busy"
            self.current_task_id = task_id
            self.current_task_start = time.time()

    def idle(self):
        with self._lock:
            self.status = "idle"
            self.current_task_id = None
            self.current_task_start = None

    def to_dict(self) -> dict:
        with self._lock:
            busy_time = None
            if self.current_task_start:
                busy_time = round(time.time() - self.current_task_start, 1)
            return {
                "node_id":      self.node_id,
                "status":       self.status,
                "capabilities": self.capabilities,
                "port":         self.port,
                "current_task": self.current_task_id,
                "busy_seconds": busy_time,
                "started_at":   self.started_at,
            }


# ── 文件操作工具 ──────────────────────────────────────────────────────────

def read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def write_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [node:{NODE_STATE.node_id}] {msg}", flush=True)


# ── 任务操作 ──────────────────────────────────────────────────────────────

def poll_task(node_id: str, capabilities: list) -> Optional[dict]:
    """
    节点主动拉取任务。

    策略：
    1. 优先抢分配给自己的任务
    2. 其次抢未分配且自己有能力执行的任务
    """
    ensure_dirs()

    for fname in sorted(os.listdir(QUEUE_DIR)):
        if not fname.endswith(".json") or fname.startswith("r_"):
            continue

        fpath = os.path.join(QUEUE_DIR, fname)
        task = read_json(fpath)
        if not task:
            continue

        task_id = task.get("id", fname[:-5])
        assigned_to = task.get("assigned_to")

        # 规则1：明确分配给当前节点
        if assigned_to == node_id:
            return _acquire_task(fpath, task, task_id, node_id)

        # 规则2：未分配，且节点有相应能力
        if assigned_to is None:
            task_type = task.get("type", "general")
            if can_node_handle(task_type, capabilities):
                return _acquire_task(fpath, task, task_id, node_id)

    return None


def _acquire_task(fpath: str, task: dict, task_id: str, node_id: str) -> Optional[dict]:
    """原子地抢占任务：rename queue → in_progress"""
    # 检查是否已被别人抢走
    if not os.path.exists(fpath):
        return None

    # 移动到 in_progress
    dest_dir = os.path.join(IN_PROGRESS_DIR, f"p_{task_id}.json")

    try:
        os.rename(fpath, dest_dir)
    except FileExistsError:
        # 已被抢走
        return None

    # 更新任务状态
    task.update({
        "status":        TaskStatus.RUNNING,
        "assigned_to":    node_id,
        "started_at":    datetime.now().isoformat(),
        "node_id":       node_id,
    })
    write_json(dest_dir, task)

    log(f"[POLL] Acquired task {task_id} (type={task.get('type')})")
    return task


def complete_task(task_id: str, result, error: str = None):
    """完成任务，写入结果文件"""
    # 查找 in_progress 中的任务
    ipath = os.path.join(IN_PROGRESS_DIR, f"p_{task_id}.json")
    if not os.path.exists(ipath):
        log(f"[COMPLETE] Task {task_id} not found in in_progress")
        return False

    task = read_json(ipath)

    # 写入结果
    result_data = {
        "task_id":      task_id,
        "result":       result,
        "completed_at": datetime.now().isoformat(),
        "node":         NODE_STATE.node_id,
        "status":       TaskStatus.DONE if not error else TaskStatus.FAILED,
    }
    if error:
        result_data["error"] = error

    rpath = os.path.join(RESULTS_DIR, f"r_{task_id}.json")
    write_json(rpath, result_data)

    # 删除 in_progress 文件
    os.remove(ipath)

    log(f"[COMPLETE] {task_id} -> {'done' if not error else 'failed'}")
    NODE_STATE.idle()
    return True


def fail_task(task_id: str, error: str):
    """标记任务失败"""
    return complete_task(task_id, None, error=error)


# ── Agent 注册 ──────────────────────────────────────────────────────────

def register_node():
    """向 agents/ 目录注册节点心跳"""
    agent_file = os.path.join(AGENTS_DIR, f"{NODE_STATE.node_id}.json")
    data = {
        "node_id":      NODE_STATE.node_id,
        "status":       "idle",
        "capabilities": NODE_STATE.capabilities,
        "port":         NODE_STATE.port,
        "last_heartbeat": datetime.now().isoformat(),
        "version":      "0.5.0",
    }
    write_json(agent_file, data)
    return agent_file


def update_heartbeat():
    """更新心跳时间戳"""
    agent_file = os.path.join(AGENTS_DIR, f"{NODE_STATE.node_id}.json")
    if os.path.exists(agent_file):
        data = read_json(agent_file) or {}
        data["last_heartbeat"] = datetime.now().isoformat()
        data["status"] = NODE_STATE.status
        write_json(agent_file, data)


# ── 任务执行 ──────────────────────────────────────────────────────────────

def execute_task(task: dict) -> dict:
    """
    执行任务，返回结果或抛出异常。
    已在 orchestrator.py/executor.py 中实现，尽量复用。
    """
    from swarm_node import execute_task as _execute
    return _execute(task, NODE_STATE.node_id)


# ── 心跳线程 ──────────────────────────────────────────────────────────────

def heartbeat_loop():
    """定期更新心跳"""
    while True:
        time.sleep(10)
        try:
            update_heartbeat()
        except Exception as e:
            log(f"[HEARTBEAT] Error: {e}")


# ── 全局状态 ─────────────────────────────────────────────────────────────

NODE_STATE: Optional[NodeState] = None
SHUTDOWN_REQUESTED = False


# ── HTTP Handler ─────────────────────────────────────────────────────────

class NodeAPIHandler(BaseHTTPRequestHandler):
    """节点 HTTP API 处理器"""

    def log_message(self, fmt, *args):
        pass  # 静默，自定义 log

    def send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Node-ID", NODE_STATE.node_id)
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            return json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            return {}

    # ── GET /status ───────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.strip("/")

        if path == "status":
            self.send_json(200, NODE_STATE.to_dict())

        elif path == "health":
            self.send_json(200, {"status": "ok", "node": NODE_STATE.node_id, "ts": datetime.now().isoformat()})

        elif path == "tasks":
            # 列出 in_progress 中的任务
            tasks = []
            for fname in os.listdir(IN_PROGRESS_DIR):
                if not fname.endswith(".json"):
                    continue
                task = read_json(os.path.join(IN_PROGRESS_DIR, fname))
                if task and task.get("node_id") == NODE_STATE.node_id:
                    tasks.append({"id": task.get("id"), "type": task.get("type"),
                                  "status": task.get("status"), "started_at": task.get("started_at")})
            self.send_json(200, {"tasks": tasks})

        elif path.startswith("tasks/"):
            task_id = path[6:]
            ipath = os.path.join(IN_PROGRESS_DIR, f"p_{task_id}.json")
            rpath = os.path.join(RESULTS_DIR, f"r_{task_id}.json")
            if os.path.exists(ipath):
                self.send_json(200, read_json(ipath))
            elif os.path.exists(rpath):
                self.send_json(200, read_json(rpath))
            else:
                self.send_json(404, {"error": "Task not found"})

        else:
            self.send_json(404, {"error": "Not found"})

    # ── POST /poll ───────────────────────────────────────────────────

    def do_POST(self):
        path = self.path.strip("/")
        body = self.read_json()

        if path == "poll":
            # 节点主动拉取任务
            task = poll_task(NODE_STATE.node_id, NODE_STATE.capabilities)
            if task:
                NODE_STATE.busy(task.get("id", "unknown"))
                self.send_json(200, {"status": "ok", "task": task})
            else:
                self.send_json(200, {"status": "no_task"})

        elif path == "complete":
            # 提交任务结果
            task_id = body.get("task_id")
            result = body.get("result")
            error = body.get("error")
            if not task_id:
                self.send_json(400, {"error": "task_id required"})
                return
            ok = complete_task(task_id, result, error)
            self.send_json(200, {"status": "ok" if ok else "error"})

        elif path == "execute":
            # 直接执行一个任务（主龙虾推送模式）
            task = body.get("task")
            if not task:
                self.send_json(400, {"error": "task required"})
                return

            task_id = task.get("id", f"direct_{int(time.time()*1000)}")
            NODE_STATE.busy(task_id)

            try:
                # 执行任务（同步）
                result = execute_task(task)
                complete_task(task_id, result)
                self.send_json(200, {"status": "ok", "task_id": task_id, "result": result})
            except Exception as e:
                fail_task(task_id, str(e))
                self.send_json(200, {"status": "error", "task_id": task_id, "error": str(e)})

        elif path == "shutdown":
            global SHUTDOWN_REQUESTED
            SHUTDOWN_REQUESTED = True
            self.send_json(200, {"status": "shutdown_requested"})

        else:
            self.send_json(404, {"error": "Not found"})


# ── 主入口 ───────────────────────────────────────────────────────────────

def main():
    global NODE_STATE

    if len(sys.argv) < 2:
        print("用法: python node_api.py <node_id> [capability1] [capability2] ...")
        print("示例: python node_api.py claw_alpha search write code")
        sys.exit(1)

    node_id = sys.argv[1]
    capabilities = sys.argv[2:] if len(sys.argv) > 2 else ["search", "write", "code"]

    # 端口：5171 + node_index（默认 claw_alpha=5171, claw_beta=5172, claw_gamma=5173）
    ports = {"claw_alpha": 5171, "claw_beta": 5172, "claw_gamma": 5173, "claw_delta": 5174}
    port = ports.get(node_id, 5171 + sum(ord(c) for c in node_id) % 100)

    NODE_STATE = NodeState(node_id, capabilities, port)
    ensure_dirs()
    register_node()

    # 注册优雅关闭
    def shutdown_handler(sig, frame):
        log("Shutdown signal received")
        # 注销节点
        agent_file = os.path.join(AGENTS_DIR, f"{node_id}.json")
        if os.path.exists(agent_file):
            os.remove(agent_file)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # 启动心跳线程
    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()

    # 启动 HTTP 服务
    server = HTTPServer(("0.0.0.0", port), NodeAPIHandler)
    log(f"API server starting on http://0.0.0.0:{port}")
    log(f"Node: {node_id}, Capabilities: {capabilities}")
    log(f"Endpoints: GET /status /health /tasks, POST /poll /complete /execute /shutdown")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
