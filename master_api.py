"""
ClawSwarm - 主龙虾 HTTP API 服务

运行在主服务器上，暴露 REST API 供外部调用（Web 界面、其他系统、CLI）。

启动：
    python master_api.py [port]   # 默认 5000

API 端点：
    任务：
        POST   /tasks              — 创建任务
        GET    /tasks              — 列出所有任务
        GET    /tasks/<id>         — 任务详情
        DELETE /tasks/<id>          — 删除任务
        GET    /tasks/<id>/result  — 获取任务结果
        POST   /tasks/<id>/retry   — 重试失败任务

    节点：
        GET    /nodes               — 列出所有节点
        GET    /nodes/<id>          — 节点详情
        POST   /nodes/<id>/assign    — 分配任务给节点
        POST   /nodes/<id>/wake      — 唤醒节点

    系统：
        GET    /health              — 健康检查
        GET    /stats               — 集群统计
        POST   /shutdown             — 关闭主服务

    WebSocket（未来）：
        WS     /ws                  — 实时任务状态推送
"""

import os, sys, json, time, uuid, threading, signal, asyncio, queue as tqueue
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

# ── 路径 ─────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, QUEUE_DIR, IN_PROGRESS_DIR, RESULTS_DIR, AGENTS_DIR, LOGS_DIR, ensure_dirs
from models import TaskStatus
from swarm_scheduler import create_task, get_online_nodes, get_all_tasks, get_task_result
from orchestrator import Orchestrator


# ── 文件操作 ──────────────────────────────────────────────────────────────

def read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [master] {msg}", flush=True)


# ── 任务仓储 ──────────────────────────────────────────────────────────────

class TaskRepo:
    """任务仓储，基于文件系统"""

    @staticmethod
    def list(status: str = None, limit: int = 100) -> List[dict]:
        """列出所有任务"""
        ensure_dirs()
        tasks = []

        # queue/
        for fname in os.listdir(QUEUE_DIR):
            if not fname.endswith(".json") or fname.startswith("r_"):
                continue
            task = read_json(os.path.join(QUEUE_DIR, fname))
            if task:
                tasks.append(task)

        # in_progress/
        for fname in os.listdir(IN_PROGRESS_DIR):
            if not fname.endswith(".json"):
                continue
            task = read_json(os.path.join(IN_PROGRESS_DIR, fname))
            if task:
                tasks.append(task)

        # results/
        for fname in os.listdir(RESULTS_DIR):
            if not fname.endswith(".json"):
                continue
            task = read_json(os.path.join(RESULTS_DIR, fname))
            if task:
                # results 文件是 r_ 开头，转成 task 格式
                task_id = fname[2:-5]  # 去掉 "r_" 前缀和 ".json" 后缀
                task["id"] = task_id
                task["_source"] = "results"
                tasks.append(task)

        # 过滤
        if status:
            tasks = [t for t in tasks if t.get("status") == status]

        # 排序：最新的在前
        tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return tasks[:limit]

    @staticmethod
    def get(task_id: str) -> Optional[dict]:
        """获取单个任务"""
        # 优先 queue
        path = os.path.join(QUEUE_DIR, f"{task_id}.json")
        if os.path.exists(path):
            return read_json(path)

        # 其次 in_progress
        path = os.path.join(IN_PROGRESS_DIR, f"p_{task_id}.json")
        if os.path.exists(path):
            return read_json(path)

        # 最后 results
        path = os.path.join(RESULTS_DIR, f"r_{task_id}.json")
        if os.path.exists(path):
            data = read_json(path)
            if data:
                data["id"] = task_id
            return data

        return None

    @staticmethod
    def result(task_id: str) -> Optional[dict]:
        """获取任务结果"""
        path = os.path.join(RESULTS_DIR, f"r_{task_id}.json")
        if os.path.exists(path):
            return read_json(path)
        return None

    @staticmethod
    def delete(task_id: str) -> bool:
        """删除任务"""
        deleted = False
        for dirname, prefix in [(QUEUE_DIR, ""), (IN_PROGRESS_DIR, "p_")]:
            path = os.path.join(dirname, f"{prefix}{task_id}.json")
            if os.path.exists(path):
                os.remove(path)
                deleted = True
        return deleted

    @staticmethod
    def retry(task_id: str) -> Optional[str]:
        """重试失败任务"""
        task = TaskRepo.get(task_id)
        if not task:
            return None
        if task.get("status") not in (TaskStatus.FAILED, TaskStatus.DONE):
            return None
        # 重新创建任务
        new_id, new_task = create_task(
            description=task.get("description", task.get("prompt", "")),
            task_type=task.get("type", "general"),
            priority=task.get("priority"),
            metadata=task.get("metadata", {}),
        )
        return new_id


# ── 节点仓储 ──────────────────────────────────────────────────────────────

class NodeRepo:
    """节点仓储"""

    @staticmethod
    def list() -> List[dict]:
        """列出所有节点"""
        ensure_dirs()
        nodes = []
        if not os.path.exists(AGENTS_DIR):
            return nodes

        for fname in os.listdir(AGENTS_DIR):
            if not fname.endswith(".json"):
                continue
            node = read_json(os.path.join(AGENTS_DIR, fname))
            if node:
                # 判断是否在线（心跳 30 秒内）
                last_hb = node.get("last_heartbeat", "")
                if last_hb:
                    try:
                        hb_time = datetime.fromisoformat(last_hb).timestamp()
                        age = time.time() - hb_time
                        node["online"] = age < 30
                        node["heartbeat_age_seconds"] = round(age, 1)
                    except Exception:
                        node["online"] = False
                else:
                    node["online"] = False
                nodes.append(node)
        return nodes

    @staticmethod
    def get(node_id: str) -> Optional[dict]:
        """获取节点详情"""
        path = os.path.join(AGENTS_DIR, f"{node_id}.json")
        if os.path.exists(path):
            return read_json(path)
        return None

    @staticmethod
    def assign_task(node_id: str, task_id: str) -> bool:
        """将任务分配给指定节点"""
        task_path = os.path.join(QUEUE_DIR, f"{task_id}.json")
        if not os.path.exists(task_path):
            task_path = os.path.join(IN_PROGRESS_DIR, f"p_{task_id}.json")
        if not os.path.exists(task_path):
            return False

        task = read_json(task_path)
        task["assigned_to"] = node_id
        write_json(task_path, task)
        log(f"[ASSIGN] Task {task_id} -> {node_id}")
        return True


# ── 全局状态 ──────────────────────────────────────────────────────────────

SHUTDOWN_REQUESTED = False


# ── HTTP Handler ─────────────────────────────────────────────────────────

class MasterAPIHandler(BaseHTTPRequestHandler):
    """主龙虾 HTTP API 处理器"""

    def log_message(self, fmt, *args):
        pass

    def send_json(self, status: int, data: dict, headers: dict = None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.wfile.write(body)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            return json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            return {}

    def parse_path(self):
        """解析路径和查询参数"""
        parsed = urlparse(self.path)
        path = parsed.path.strip("/")
        query = parse_qs(parsed.query)
        # 简化：query 只取第一个值
        query_simple = {k: v[0] if len(v) == 1 else v for k, v in query.items()}
        return path, query_simple

    # ── 任务 API ────────────────────────────────────────────────────────

    def do_GET(self):
        path, query = self.parse_path()

        # GET /tasks
        if path == "tasks":
            status = query.get("status")
            limit = int(query.get("limit", 100))
            tasks = TaskRepo.list(status=status, limit=limit)
            self.send_json(200, {"tasks": tasks, "count": len(tasks)})

        # GET /tasks/<id>
        elif path.startswith("tasks/") and "/result" not in path:
            task_id = path[6:]
            task = TaskRepo.get(task_id)
            if task:
                self.send_json(200, task)
            else:
                self.send_json(404, {"error": "Task not found"})

        # GET /tasks/<id>/result
        elif path.startswith("tasks/") and path.endswith("/result"):
            task_id = path[6:-8]
            result = TaskRepo.result(task_id)
            if result:
                self.send_json(200, result)
            else:
                self.send_json(404, {"error": "Result not found"})

        # GET /nodes
        elif path == "nodes":
            nodes = NodeRepo.list()
            self.send_json(200, {"nodes": nodes, "count": len(nodes)})

        # GET /nodes/<id>
        elif path.startswith("nodes/") and "/" not in path[6:]:
            node_id = path[6:]
            node = NodeRepo.get(node_id)
            if node:
                self.send_json(200, node)
            else:
                self.send_json(404, {"error": "Node not found"})

        # GET /stats
        elif path == "stats":
            nodes = NodeRepo.list()
            tasks = TaskRepo.list(limit=1000)
            stats = {
                "nodes": {
                    "total": len(nodes),
                    "online": sum(1 for n in nodes if n.get("online"))
                },
                "tasks": {
                    "total": len(tasks),
                    "pending": sum(1 for t in tasks if t.get("status") in ("pending", "queued")),
                    "running": sum(1 for t in tasks if t.get("status") == "running"),
                    "done": sum(1 for t in tasks if t.get("status") == "done"),
                    "failed": sum(1 for t in tasks if t.get("status") == "failed"),
                }
            }
            self.send_json(200, stats)

        # GET /health
        elif path == "health":
            self.send_json(200, {
                "status": "ok",
                "ts": datetime.now().isoformat(),
                "version": "0.5.0",
            })

        else:
            self.send_json(404, {"error": "Not found", "path": self.path})

    # ── POST API ───────────────────────────────────────────────────────

    def do_POST(self):
        path, query = self.parse_path()
        body = self.read_json()

        # POST /tasks — 创建任务
        if path == "tasks":
            description = body.get("description") or body.get("prompt", "")
            task_type = body.get("type", "general")
            priority = body.get("priority")
            metadata = body.get("metadata", {})
            assigned_to = body.get("assigned_to")  # 可选：指定节点

            if not description:
                self.send_json(400, {"error": "description required"})
                return

            task_id, task = create_task(description, task_type, priority, metadata)
            if assigned_to:
                task["assigned_to"] = assigned_to
                path_to_write = os.path.join(QUEUE_DIR, f"{task_id}.json")
                write_json(path_to_write, task)
            else:
                # 未指定节点：加入后台处理队列
                path_to_write = os.path.join(QUEUE_DIR, f"{task_id}.json")
                write_json(path_to_write, task)
                _enqueue_task(task_id, task)

            log(f"[CREATE] {task_id} (type={task_type}) -> {assigned_to or 'queued for processing'}")
            self.send_json(201, {"task_id": task_id, "task": task})

        # POST /tasks/<id>/retry
        elif path.startswith("tasks/") and path.endswith("/retry"):
            task_id = path[6:-6]
            new_id = TaskRepo.retry(task_id)
            if new_id:
                self.send_json(200, {"task_id": new_id, "message": "Task resubmitted"})
            else:
                self.send_json(400, {"error": "Cannot retry task (not failed/done or not found)"})

        # POST /nodes/<id>/assign
        elif path.startswith("nodes/") and path.endswith("/assign"):
            node_id = path[6:-7]
            task_id = body.get("task_id")
            if not task_id:
                self.send_json(400, {"error": "task_id required"})
                return
            ok = NodeRepo.assign_task(node_id, task_id)
            self.send_json(200, {"ok": ok})

        # POST /nodes/<id>/wake
        elif path.startswith("nodes/") and path.endswith("/wake"):
            node_id = path[6:-5]
            node = NodeRepo.get(node_id)
            if not node:
                self.send_json(404, {"error": "Node not found"})
                return
            # 未来：通过 HTTP 唤醒节点
            self.send_json(200, {"message": f"Wake signal sent to {node_id}", "port": node.get("port")})

        # POST /shutdown
        elif path == "shutdown":
            global SHUTDOWN_REQUESTED
            SHUTDOWN_REQUESTED = True
            self.send_json(200, {"status": "shutdown_requested"})

        else:
            self.send_json(404, {"error": "Not found"})

    # ── DELETE API ────────────────────────────────────────────────────

    def do_DELETE(self):
        path, _ = self.parse_path()

        if path.startswith("tasks/") and "/" not in path[6:]:
            task_id = path[6:]
            ok = TaskRepo.delete(task_id)
            self.send_json(200, {"deleted": ok})
        else:
            self.send_json(404, {"error": "Not found"})

    # ── CORS 预检 ─────────────────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()


# ── 任务队列后台处理器 ───────────────────────────────────────────────────

# 任务队列（用于解耦 HTTP 请求和实际处理）
_task_queue: "tqueue.Queue" = tqueue.Queue()
_orc = None  # 单例 orchestrator


def _enqueue_task(task_id: str, task: dict):
    """将任务加入处理队列"""
    _task_queue.put((task_id, task))
    log(f"[QUEUED] {task_id} queued for processing")


def _process_queue_loop():
    """
    后台线程：从队列中取出任务，调用 orchestrator 处理。
    循环运行，直到 SHUTDOWN_REQUESTED。
    """
    global _orc
    _orc = Orchestrator(timeout=180.0, use_llm=False)

    log("[BG] Queue processor thread started")

    while not SHUTDOWN_REQUESTED:
        task_id = None
        task = None

        # 非阻塞取出任务
        try:
            item = _task_queue.get(block=True, timeout=1.0)
            task_id, task = item
        except tqueue.Empty:
            # 队列空，扫描 queue/ 目录有没有新任务
            _scan_queue_dir()
            continue

        if task_id is None:
            continue

        # 移动: queue/ → in_progress/
        src = os.path.join(QUEUE_DIR, f"{task_id}.json")
        dst = os.path.join(IN_PROGRESS_DIR, f"p_{task_id}.json")
        if os.path.exists(src):
            os.rename(src, dst)

        task["status"] = "running"
        task["started_at"] = datetime.now().isoformat()
        write_json(dst, task)

        log(f"[BG] Processing task {task_id}: {task.get('description', '')[:60]}")

        # 调用 orchestrator 处理
        start = time.time()
        try:
            desc = task.get("description") or task.get("prompt", "")
            result = _orc.run(desc)
            duration = time.time() - start

            # 构建结果
            result_data = {
                "task_id": task_id,
                "status": "done" if result.success else "failed",
                "result": result.final_output,
                "duration_seconds": duration,
                "completed_at": datetime.now().isoformat(),
                "errors": result.errors,
            }
            log(f"[BG] Task {task_id} done ({duration:.1f}s): success={result.success}")

        except Exception as e:
            duration = time.time() - start
            result_data = {
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
                "duration_seconds": duration,
                "completed_at": datetime.now().isoformat(),
            }
            log(f"[BG] Task {task_id} failed: {e}")

        # 写结果到 results/
        result_path = os.path.join(RESULTS_DIR, f"r_{task_id}.json")
        write_json(result_path, result_data)

        # 从 in_progress/ 删除
        if os.path.exists(dst):
            os.remove(dst)

    log("[BG] Queue processor thread stopped")


def _scan_queue_dir():
    """扫描 queue/ 目录，发现新任务则加入处理队列"""
    try:
        for fname in os.listdir(QUEUE_DIR):
            if not fname.endswith(".json") or fname.startswith("r_") or fname.startswith("p_"):
                continue
            task_id = fname[:-5]  # 去掉 .json
            path = os.path.join(QUEUE_DIR, fname)
            task = read_json(path)
            if task and task.get("status") == "pending" and not task.get("assigned_to"):
                # 未分配的任务，加入队列处理
                _task_queue.put((task_id, task))
                log(f"[BG] Discovered queued task {task_id}")
    except Exception as e:
        pass  # 静默忽略扫描错误


# ── 主入口 ────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ClawSwarm Master API Server")
    parser.add_argument("--port", "-p", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args(sys.argv[1:])

    ensure_dirs()

    # 启动后台任务处理线程
    bg_thread = threading.Thread(target=_process_queue_loop, daemon=True, name="QueueProcessor")
    bg_thread.start()
    log("[BG] Background queue processor started")

    def shutdown_handler(sig, frame):
        log("Shutdown signal received")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    server = HTTPServer((args.host, args.port), MasterAPIHandler)
    log(f"Master API server starting on http://{args.host}:{args.port}")
    log("Endpoints:")
    log("  GET  /health              健康检查")
    log("  GET  /stats               集群统计")
    log("  GET  /tasks               列出所有任务")
    log("  POST /tasks               创建任务")
    log("  GET  /tasks/<id>          任务详情")
    log("  DELETE /tasks/<id>        删除任务")
    log("  GET  /tasks/<id>/result   获取结果")
    log("  POST /tasks/<id>/retry    重试任务")
    log("  GET  /nodes               列出所有节点")
    log("  GET  /nodes/<id>          节点详情")
    log("  POST /nodes/<id>/assign   分配任务")
    log("  POST /nodes/<id>/wake     唤醒节点")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
