# networking.py — ClawSwarm 跨公网通信模块
#
# 架构：Hub-Spoke 反向轮询模型
#   Hub:  运行在"主控端"（你的 Windows），port 18080
#   Agent: 运行在"执行端"（KimiClaw VM），作为 HTTP client 连 Hub
#
# 关键设计：
#   1. Hub 被动，Agent 主动轮询（不需要 inbound 端口暴露）
#   2. 不需要任何 tunnel / SSH / 公网 IP
#   3. Agent 端只需要能访问 Hub 的 URL（Hub 必须对 Agent 可见）
#
# 使用：
#   Hub 端：python networking.py hub [--port 18080]
#   Agent 端：python networking.py agent --hub-url http://<hub-ip>:18080 --agent-id kimi-claw

import os, sys, time, json, threading, queue as tqueue, argparse
from datetime import datetime
from pathlib import Path

# ── 路径配置 ────────────────────────────────────────────────────────────────

_swarm_root = os.path.dirname(os.path.abspath(__file__))
HUB_TASK_DIR   = os.path.join(_swarm_root, "swarm_data", "hub_tasks")
HUB_RESULT_DIR = os.path.join(_swarm_root, "swarm_data", "hub_results")
os.makedirs(HUB_TASK_DIR, exist_ok=True)
os.makedirs(HUB_RESULT_DIR, exist_ok=True)

# ── HubServer（Hub 端）──────────────────────────────────────────────────────

class HubServer:
    """
    Hub 端：运行在主控端，暴露 task queue HTTP 端点。
    Agent 作为 HTTP client 轮询 Hub。

    端点（全部 JSON）：
        POST /hub/register       — agent 注册（返回 OK）
        GET  /hub/agents        — 列出所有注册的 agent
        GET  /hub/queue/<id>    — agent 轮询自己的任务队列（原子 pop）
        POST /hub/submit_task   — 主控端提交任务给指定 agent
        POST /hub/submit/<tid>  — agent 提交任务结果
        GET  /hub/result/<tid>  — 主控端获取任务结果
        GET  /hub/status         — Hub 状态
    """

    def __init__(self):
        self._agents  = {}   # agent_id -> {capabilities, name, registered_at, last_poll}
        self._running = True

    def register(self, agent_id: str, capabilities: list, name: str = "") -> dict:
        self._agents[agent_id] = {
            "capabilities": capabilities or [],
            "name":         name or agent_id,
            "registered_at": datetime.now().isoformat(),
            "last_poll":     time.time(),
        }
        os.makedirs(os.path.join(HUB_TASK_DIR, agent_id), exist_ok=True)
        return {"status": "ok", "agent_id": agent_id}

    def enqueue_task(self, agent_id: str, task: dict) -> str:
        """主控端提交任务给指定 agent，返回 task_id"""
        task_id = task.get("task_id") or f"t_{int(time.time()*1000)}"
        fpath = os.path.join(HUB_TASK_DIR, agent_id, f"{task_id}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump({**task, "task_id": task_id, "queued_at": datetime.now().isoformat()},
                      f, ensure_ascii=False, indent=2)
        return task_id

    def poll_queue(self, agent_id: str) -> list:
        """Agent 轮询自己的任务队列，原子 pop"""
        if agent_id in self._agents:
            self._agents[agent_id]["last_poll"] = time.time()
        agent_dir = os.path.join(HUB_TASK_DIR, agent_id)
        if not os.path.isdir(agent_dir):
            return []
        tasks = []
        for fname in sorted(os.listdir(agent_dir)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(agent_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    tasks.append(json.load(f))
                os.remove(fpath)
            except Exception:
                pass
        return tasks

    def submit_result(self, task_id: str, result: dict) -> dict:
        """Agent 提交任务结果"""
        fpath = os.path.join(HUB_RESULT_DIR, f"{task_id}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump({
                "task_id":      task_id,
                "result":       result,
                "completed_at": datetime.now().isoformat(),
                "status":       "done",
            }, f, ensure_ascii=False, indent=2)
        return {"status": "ok", "task_id": task_id}

    def get_result(self, task_id: str) -> dict | None:
        fpath = os.path.join(HUB_RESULT_DIR, f"{task_id}.json")
        if not os.path.exists(fpath):
            return None
        with open(fpath, encoding="utf-8") as f:
            return json.load(f)

    def list_agents(self) -> list:
        return [
            {**info, "agent_id": aid,
             "idle": (time.time() - info["last_poll"]) < 30}
            for aid, info in self._agents.items()
        ]

    def hub_status(self) -> dict:
        pending = sum(
            len(os.listdir(os.path.join(HUB_TASK_DIR, d)))
            for d in os.listdir(HUB_TASK_DIR)
            if os.path.isdir(os.path.join(HUB_TASK_DIR, d))
        )
        return {
            "status":        "ok",
            "agents":        len(self._agents),
            "pending_tasks":  pending,
            "results":       len([f for f in os.listdir(HUB_RESULT_DIR) if f.endswith(".json")]),
            "uptime":        time.time(),
        }


# ── HubAgent（Agent 端，运行在 VM）────────────────────────────────────────

class HubAgent:
    """
    Agent 端：运行在 KimiClaw VM 上，HTTP client 连 Hub。
    轮询 Hub 的任务队列，拿到任务后执行，结果 POST 回 Hub。

    用法（原生执行，无 adapter）：
        agent = HubAgent(hub_url="http://<hub-ip>:18080", agent_id="kimi-claw")
        agent.start()

    用法（通过 adapter 执行）：
        agent = HubAgent(
            hub_url="http://<hub-ip>:18080",
            agent_id="hermes-01",
            adapter_type="hermes",
            adapter_config={"hermes_bin": "hermes", "model": "qwen2.5:72b"},
        )
        agent.start()

    adapter_type 支持: openclaw, hermes, evolver, None (原生 echo)
    """

    def __init__(self, hub_url: str, agent_id: str, capabilities: list = None,
                 poll_interval: float = 3.0,
                 adapter_type: str = None, adapter_config: dict = None):
        self.hub_url       = hub_url.rstrip("/")
        self.agent_id      = agent_id
        self.poll_interval = poll_interval
        self._running      = False
        self._thread       = None
        self._adapter      = None

        # Build adapter if requested
        if adapter_type:
            from agent_adapter import get_adapter
            self._adapter = get_adapter(adapter_type, agent_id, adapter_config or {})
            self.capabilities = self._adapter.capabilities
        else:
            self.capabilities = capabilities or ["fetch", "exec", "python", "shell"]

    def _http(self, method: str, path: str, data: dict = None) -> dict:
        import urllib.request, urllib.error
        url = f"{self.hub_url}{path}"
        body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body,
                                    headers={"Content-Type": "application/json"})
        req.get_method = lambda: method
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}", "body": e.read().decode("utf-8", errors="replace")}
        except Exception as e:
            return {"error": str(e)}

    def register(self) -> bool:
        r = self._http("POST", "/hub/register", {
            "agent_id":     self.agent_id,
            "capabilities": self.capabilities,
            "name":         self.agent_id,
        })
        return r.get("status") == "ok"

    def poll_tasks(self) -> list:
        r = self._http("GET", f"/hub/queue/{self.agent_id}")
        return r.get("tasks", []) if isinstance(r, dict) else []

    def submit_result(self, task_id: str, result: dict) -> bool:
        r = self._http("POST", f"/hub/submit/{task_id}", {"result": result})
        return r.get("status") == "ok"

    def execute_task(self, task: dict) -> dict:
        """
        执行单个任务。
        如果有 adapter，委托给 adapter.execute()（async → 同步）。
        否则使用默认 echo 行为。
        """
        if self._adapter:
            return self._execute_via_adapter(task)
        # 原生 echo 行为
        task_type = task.get("type") or task.get("task_type", "general")
        prompt    = task.get("prompt") or task.get("description", "")
        return {
            "mode":        task_type,
            "prompt":      prompt[:200],
            "status":     "executed",
            "executed_at": datetime.now().isoformat(),
        }

    def _execute_via_adapter(self, task: dict) -> dict:
        """通过 adapter 执行任务（同步 wrapper）"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            # 已有事件循环，用 nest_asyncio 或新线程
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self._adapter.execute(task))
                return future.result(timeout=300)
        else:
            return asyncio.run(self._adapter.execute(task))

    def _poll_loop(self):
        print(f"[HubAgent] Polling {self.hub_url} every {self.poll_interval}s")
        while self._running:
            try:
                tasks = self.poll_tasks()
                for task in tasks:
                    task_id = task.get("task_id", "?")
                    desc    = (task.get("prompt") or task.get("description") or "")[:80]
                    print(f"[HubAgent] Task {task_id}: {desc}")
                    result = self.execute_task(task)
                    ok     = self.submit_result(task_id, result)
                    print(f"[HubAgent] Result for {task_id}: {'ok' if ok else 'FAILED'}")
            except Exception as e:
                print(f"[HubAgent] Error: {e}")
            time.sleep(self.poll_interval)

    def start(self, background: bool = True) -> bool:
        # 启动 adapter（如果有的话）
        if self._adapter:
            if not self._adapter.start():
                print(f"[HubAgent] Adapter {self._adapter} failed to start")
                return False
            print(f"[HubAgent] Adapter started: {self._adapter}")
        ok = self.register()
        if not ok:
            print(f"[HubAgent] Registration failed at {self.hub_url}")
            return False
        print(f"[HubAgent] Registered as {self.agent_id}")
        self._running = True
        self._thread  = threading.Thread(target=self._poll_loop, daemon=True,
                                         name=f"HubAgent-{self.agent_id}")
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self._adapter:
            self._adapter.stop()
        if self._thread:
            self._thread.join(timeout=5)


# ── HubClient（主控端 client，主动下发任务）────────────────────────────────

class HubClient:
    """
    主控端 client：主动向远程 Hub 提交任务、轮询结果。
    用于主控端主动向 VM 下发任务。

    用法：
        client = HubClient(hub_url="http://<vm-public-ip>:18080")
        task_id = client.submit_task(agent_id="kimi-claw",
                                     task={"prompt": "do something", "type": "fetch"})
        result = client.wait_result(task_id, timeout=120)
    """

    def __init__(self, hub_url: str):
        self.hub_url = hub_url.rstrip("/")

    def _http(self, method: str, path: str, data: dict = None) -> dict:
        import urllib.request, urllib.error
        url  = f"{self.hub_url}{path}"
        body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8") if data else None
        req  = urllib.request.Request(url, data=body,
                                      headers={"Content-Type": "application/json"})
        req.get_method = lambda: method
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}

    def list_agents(self) -> list:
        r = self._http("GET", "/hub/agents")
        return r.get("agents", []) if isinstance(r, dict) else []

    def submit_task(self, agent_id: str, task: dict) -> str:
        tid = task.get("task_id") or f"t_{int(time.time()*1000)}"
        r   = self._http("POST", "/hub/submit_task", {
            "agent_id": agent_id,
            "task":     {**task, "task_id": tid},
        })
        if r.get("status") == "ok":
            return r.get("task_id", tid)
        raise RuntimeError(f"Submit failed: {r}")

    def poll_result(self, task_id: str) -> dict | None:
        r = self._http("GET", f"/hub/result/{task_id}")
        if "error" in r and r.get("status") == 404:
            return None
        return r if isinstance(r, dict) and "task_id" in r else None

    def wait_result(self, task_id: str, timeout: float = 120,
                    poll_interval: float = 3.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.poll_result(task_id)
            if result:
                return result
            time.sleep(poll_interval)
        raise TimeoutError(f"Task {task_id} timed out after {timeout}s")


# ── HTTP 服务器（Hub 端运行）──────────────────────────────────────────────

def _make_handler(hub: HubServer):
    import http.server, socketserver, re
    from urllib.parse import urlparse

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _json(self, code: int, data: dict):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length", 0)))

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin",  "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path.rstrip("/")

            if path == "/hub/status":
                return self._json(200, hub.hub_status())

            if path == "/hub/agents":
                return self._json(200, {"agents": hub.list_agents()})

            m = re.match(r"^/hub/queue/([^/]+)$", path)
            if m:
                tasks = hub.poll_queue(m.group(1))
                return self._json(200, {"tasks": tasks, "count": len(tasks)})

            m = re.match(r"^/hub/result/([^/]+)$", path)
            if m:
                r = hub.get_result(m.group(1))
                if r:
                    return self._json(200, r)
                return self._json(404, {"error": "NOT_FOUND"})

            self._json(404, {"error": f"Unknown path: {path}"})

        def do_POST(self):
            path = urlparse(self.path).path.rstrip("/")
            body = self._body()

            if path == "/hub/register":
                data = json.loads(body) if body else {}
                r = hub.register(data.get("agent_id",""),
                                 data.get("capabilities", []),
                                 data.get("name", ""))
                return self._json(200, r)

            if path == "/hub/submit_task":
                data = json.loads(body) if body else {}
                tid = hub.enqueue_task(data.get("agent_id",""), data.get("task", {}))
                return self._json(200, {"status": "ok", "task_id": tid})

            m = re.match(r"^/hub/submit/([^/]+)$", path)
            if m:
                data = json.loads(body) if body else {}
                r = hub.submit_result(m.group(1), data.get("result", {}))
                return self._json(200, r)

            self._json(404, {"error": f"Unknown path: {path}"})

        def log_message(self, fmt, *args):
            print(f"[Hub {datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    return Handler


def run_hub(port: int = 18080, host: str = "0.0.0.0"):
    import socketserver, threading
    hub     = HubServer()
    Handler = _make_handler(hub)
    srv     = socketserver.ThreadingTCPServer((host, port), Handler)
    srv.allow_reuse_address = True
    print(f"Hub listening on http://{host}:{port}")
    print(f"  GET  /hub/status         — Hub 状态")
    print(f"  GET  /hub/agents         — 列出 agent")
    print(f"  GET  /hub/queue/<id>     — agent 轮询任务")
    print(f"  POST /hub/register       — agent 注册")
    print(f"  POST /hub/submit_task    — 提交任务")
    print(f"  POST /hub/submit/<tid>   — agent 提交结果")
    print(f"  GET  /hub/result/<tid>   — 获取结果")
    t = threading.Thread(target=srv.serve_forever, daemon=True, name="HubServer")
    t.start()
    t.join()  # 阻塞直到进程被 kill


# ── 主入口 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ClawSwarm Hub Networking")
    ap.add_argument("mode", choices=["hub", "agent", "client"],
                    help="hub=运行 Hub 服务器, agent=运行 Agent 客户端, client=交互模式")
    ap.add_argument("--port",      type=int,   default=18080, help="Hub 监听端口")
    ap.add_argument("--host",       default="0.0.0.0",         help="Hub 绑定地址")
    ap.add_argument("--hub-url",    default="http://localhost:18080",
                                                            help="Hub URL（agent/client 用）")
    ap.add_argument("--agent-id",   default="kimi-claw",       help="Agent ID")
    ap.add_argument("--capabilities", default="fetch,exec,python,shell",
                                                            help="Agent 能力列表")
    ap.add_argument("--task",       default=None,               help="(client) 要下发的任务描述")
    ap.add_argument("--task-type",  default="fetch",            help="(client) 任务类型")
    ap.add_argument("--poll-interval", type=float, default=3.0, help="轮询间隔（秒）")
    ap.add_argument("--adapter-type",  default=None,
                    help="Agent adapter 类型 (hermes/evolver/openclaw)")
    ap.add_argument("--adapter-config", default=None,
                    help="Adapter 配置 JSON 字符串，如 '{\"hermes_bin\":\"hermes\"}'")
    args = ap.parse_args()

    if args.mode == "hub":
        run_hub(port=args.port, host=args.host)

    elif args.mode == "agent":
        caps = [c.strip() for c in args.capabilities.split(",")]
        adapter_config = json.loads(args.adapter_config) if args.adapter_config else None
        agent = HubAgent(
            hub_url=args.hub_url, agent_id=args.agent_id,
            capabilities=caps, poll_interval=args.poll_interval,
            adapter_type=args.adapter_type, adapter_config=adapter_config,
        )
        ok = agent.start(background=False)
        if ok:
            try:
                while agent._running:
                    time.sleep(1)
            except KeyboardInterrupt:
                agent.stop()

    elif args.mode == "client":
        client = HubClient(args.hub_url)
        status = client._http("GET", "/hub/status")
        print("Hub status:", json.dumps(status, indent=2, ensure_ascii=False))
        agents = client.list_agents()
        print(f"Agents ({len(agents)}):", json.dumps(agents, indent=2, ensure_ascii=False))
        if args.task:
            agents_online = [a for a in agents if a.get("idle")]
            if not agents_online:
                print("No online agents!")
            else:
                target = agents_online[0]["agent_id"]
                tid = client.submit_task(target, {"prompt": args.task, "type": args.task_type})
                print(f"Task submitted: {tid}")
                result = client.wait_result(tid, timeout=120)
                print("Result:", json.dumps(result, indent=2, ensure_ascii=False))
