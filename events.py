"""
ClawSwarm - WebSocket 实时事件服务器

推送以下事件到所有连接的客户端：
  - task.started / task.completed / task.failed
  - checkpoint.pending / checkpoint.approved / checkpoint.rejected
  - node.online / node.offline
  - metric.* (定期推送指标)

启动：
    python events.py [--port 8765]

WebSocket 端点：
    ws://localhost:8765/ws

客户端示例（JavaScript）：
    const ws = new WebSocket("ws://localhost:8765/ws");
    ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
        console.log(event.type, event.data);
    };

    // 订阅特定事件
    ws.send(JSON.stringify({action: "subscribe", events: ["task.*", "node.*"]}));

    // 取消订阅
    ws.send(JSON.stringify({action: "unsubscribe", events: ["node.*"]}));
"""

import os, sys, json, time, threading, asyncio, logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Set, List, Optional
from datetime import datetime
from collections import defaultdict
try:
    from websockets.server import WebSocketServerProtocol, serve as ws_serve
    import websockets
except ImportError:
    WebSocketServerProtocol = object
    ws_serve = None

WEBSOCKETS_AVAILABLE = 'ws_serve' in dir() and ws_serve is not None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import LOGS_DIR, BASE_DIR
from observability import EventEmitter, events

os.makedirs(LOGS_DIR, exist_ok=True)

# ── 配置 ─────────────────────────────────────────────────────────────────

WS_HOST    = os.environ.get("CLAWSWARM_WS_HOST", "0.0.0.0")
WS_PORT    = int(os.environ.get("CLAWSWARM_WS_PORT", "8765"))
METRICS_INTERVAL = float(os.environ.get("CLAWSWARM_METRICS_INTERVAL", "10.0"))

# ── 事件过滤器 ─────────────────────────────────────────────────────────

class EventFilter:
    """
    支持 glob 风格的过滤：
      "task.*"      — 所有 task 事件
      "task.done"   — 仅 task.done
      "checkpoint.*" — 所有 checkpoint 事件
    """

    @staticmethod
    def matches(event_type: str, pattern: str) -> bool:
        if pattern == "*":
            return True
        if "*" in pattern:
            import fnmatch
            return fnmatch.fnmatch(event_type, pattern)
        return event_type == pattern

    def __init__(self):
        self._patterns: Set[str] = set()

    def add(self, pattern: str):
        self._patterns.add(pattern)

    def remove(self, pattern: str):
        self._patterns.discard(pattern)

    def matches_any(self, event_type: str) -> bool:
        if not self._patterns:
            return True  # 空过滤 = 全部
        return any(self.matches(event_type, p) for p in self._patterns)


# ── 客户端 ──────────────────────────────────────────────────────────────

class WSClient:
    def __init__(self, websocket, client_id: str):
        self.websocket = websocket
        self.client_id = client_id
        self.filter = EventFilter()
        self.subscribed: Set[str] = set()
        self.remote_ip: str = websocket.remote_address[0] if websocket.remote_address else "unknown"
        self.connected_at = datetime.now().isoformat()

    def matches(self, event_type: str) -> bool:
        return self.filter.matches_any(event_type)

    async def send(self, event: dict):
        try:
            await self.websocket.send(json.dumps(event, ensure_ascii=False))
        except Exception:
            pass


# ── WebSocket 服务 ─────────────────────────────────────────────────────

class EventServer:
    """
    WebSocket 事件推送服务器。

    用法:
        server = EventServer()
        server.start()
        server.broadcast("task.completed", {"task_id": "t_001"})
        server.stop()
    """

    def __init__(self, host: str = WS_HOST, port: int = WS_PORT):
        self.host = host
        self.port = port
        self.clients: Dict[str, WSClient] = {}
        self._lock = threading.RLock()
        self._counter = 0
        self._running = False
        self._ws_server = None
        self._http_server = None
        self._metrics_thread = None

        # 注册事件监听器
        events.on(self._on_event)

        # 历史事件（最近 100 条）
        self._history: List[dict] = []

    def _gen_client_id(self) -> str:
        self._counter += 1
        return f"c_{self._counter}_{int(time.time()*1000)}"

    def _on_event(self, event: dict):
        """收到事件后广播给所有匹配的客户端"""
        asyncio.create_task(self._broadcast(event))

    async def _broadcast(self, event: dict):
        with self._lock:
            clients_snapshot = list(self.clients.values())

        disconnected = []
        for client in clients_snapshot:
            if client.matches(event.get("type", "")):
                await client.send(event)
            if client.websocket.close_code is not None:
                disconnected.append(client.client_id)

        # 清理断开的客户端
        if disconnected:
            with self._lock:
                for cid in disconnected:
                    self.clients.pop(cid, None)

    async def _handle_client(self, websocket: WebSocketServerProtocol, path: str):
        """处理单个 WebSocket 客户端连接"""
        client_id = self._gen_client_id()
        client = WSClient(websocket, client_id)

        with self._lock:
            self.clients[client_id] = client

        print(f"[events] Client connected: {client_id} ({client.remote_ip})")
        await self._send_system(client, "connected", {"client_id": client_id})

        try:
            async for raw in websocket:
                await self._handle_message(client, raw)
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except Exception as e:
            print(f"[events] Client {client_id} error: {e}")
        finally:
            with self._lock:
                self.clients.pop(client_id, None)
            print(f"[events] Client disconnected: {client_id}")

    async def _handle_message(self, client: WSClient, raw: str):
        """处理客户端发来的消息（订阅/取消订阅）"""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        action = msg.get("action")
        if action == "subscribe":
            for pattern in msg.get("events", []):
                client.filter.add(pattern)
                client.subscribed.add(pattern)
            await self._send_system(client, "subscribed", {"patterns": list(client.subscribed)})

        elif action == "unsubscribe":
            for pattern in msg.get("events", []):
                client.filter.remove(pattern)
                client.subscribed.discard(pattern)
            await self._send_system(client, "unsubscribed", {"patterns": list(client.subscribed)})

        elif action == "ping":
            await client.send({"type": "pong", "ts": datetime.now().isoformat()})

        elif action == "history":
            await self._send_system(client, "history", {"events": self._history[-50:]})

    async def _send_system(self, client: WSClient, sub_type: str, data: dict):
        await client.send({
            "type":    f"system.{sub_type}",
            "ts":      datetime.now().isoformat(),
            "service": "clawswarm-events",
            "data":    data,
        })

    async def _metrics_loop(self):
        """定期推送指标"""
        while self._running:
            await asyncio.sleep(METRICS_INTERVAL)
            try:
                from observability import get_metrics
                m = get_metrics()
                await self.broadcast("metrics.interval", {
                    "metrics": m.export_json(),
                })
            except Exception:
                pass

    async def start_async(self):
        """异步启动"""
        self._running = True
        print(f"[events] WebSocket server starting on ws://{self.host}:{self.port}")
        print(f"[events] Metrics push interval: {METRICS_INTERVAL}s")

        async with ws_serve(self._handle_client, self.host, self.port) as ws:
            metrics_task = asyncio.create_task(self._metrics_loop())
            print(f"[events] Server ready. Connect: ws://localhost:{self.port}/ws")
            try:
                await asyncio.Future()  # 永久运行
            finally:
                metrics_task.cancel()

    def start(self):
        """同步启动（在新线程中）"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.start_async())

    def start_background(self):
        """启动为后台守护线程"""
        thread = threading.Thread(target=self.start, daemon=True)
        thread.start()
        print(f"[events] Started in background thread")
        return thread

    def stop(self):
        self._running = False

    async def broadcast(self, event_type: str, data: dict = None):
        """主动广播事件"""
        event = {
            "type":    event_type,
            "ts":      datetime.now().isoformat(),
            "service": "clawswarm-events",
            "data":    data or {},
        }
        # 存入历史
        self._history.append(event)
        if len(self._history) > 100:
            self._history = self._history[-100:]
        await self._broadcast(event)

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "clients": len(self.clients),
                "client_list": [
                    {"id": c.client_id, "ip": c.remote_ip, "subscribed": list(c.subscribed)}
                    for c in self.clients.values()
                ],
                "history_size": len(self._history),
            }


# ── HTTP 健康检查端点（与 WebSocket 共用端口）────────────────────────────

class WSHTTPHandler(BaseHTTPRequestHandler):
    """提供 HTTP 健康检查（用于负载均衡器探测）"""

    server: Optional[HTTPServer] = None

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            stats = EVENT_SERVER.get_stats() if "EVENT_SERVER" in globals() else {}
            self.wfile.write(json.dumps({
                "status": "ok",
                "service": "clawswarm-events",
                "ts": datetime.now().isoformat(),
                "clients": stats.get("clients", 0),
            }, ensure_ascii=False).encode())

        elif self.path == "/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            stats = EVENT_SERVER.get_stats() if "EVENT_SERVER" in globals() else {}
            self.wfile.write(json.dumps(stats, ensure_ascii=False).encode())

        elif self.path.startswith("/ws") or self.path == "/":
            # 重定向到 WebSocket（客户端需用 ws:// URL 直接连接）
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ClawSwarm Event Server - use WebSocket protocol")

        else:
            self.send_response(404)
            self.end_headers()


# ── 全局单例 ─────────────────────────────────────────────────────────

EVENT_SERVER: Optional[EventServer] = None

def get_server() -> EventServer:
    global EVENT_SERVER
    if EVENT_SERVER is None:
        EVENT_SERVER = EventServer()
    return EVENT_SERVER


# ── 兼容 EventEmitter 接口 ─────────────────────────────────────────────

# 让 observability.events 自动广播到 WebSocket
_original_emit = events.emit

def _patched_emit(event_type: str, data: dict = None):
    _original_emit(event_type, data)
    # 尝试广播到 WebSocket
    if EVENT_SERVER and EVENT_SERVER._running:
        asyncio.create_task(EVENT_SERVER.broadcast(event_type, data))

events.emit = _patched_emit


# ── 主入口 ─────────────────────────────────────────────────────────────

async def main_async():
    server = get_server()
    server._running = True
    print(f"""
╔══════════════════════════════════════════════════╗
║     ClawSwarm Event Server  (WebSocket)          ║
╠══════════════════════════════════════════════════╣
║  WebSocket: ws://{WS_HOST}:{WS_PORT}/ws                   ║
║  HTTP:      http://{WS_HOST}:{WS_PORT}/health             ║
║  Stats:     http://{WS_HOST}:{WS_PORT}/stats              ║
╠══════════════════════════════════════════════════╣
║  Events: task.* | checkpoint.* | node.* | metrics.interval
╚══════════════════════════════════════════════════╝
""")
    await server.start_async()


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[events] Shutting down")
        sys.exit(0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ClawSwarm Event Server")
    parser.add_argument("--host", default=WS_HOST)
    parser.add_argument("--port", type=int, default=WS_PORT)
    parser.add_argument("--interval", type=float, default=METRICS_INTERVAL,
                       help="Metrics push interval (seconds)")
    args = parser.parse_args(sys.argv[1:])

    events.WS_HOST = args.host
    events.WS_PORT = args.port
    events.METRICS_INTERVAL = args.interval

    # 检查 websockets 包
    if not hasattr(websockets, 'serve'):
        print("ERROR: websockets package not installed.")
        print("Install: pip install websockets")
        sys.exit(1)

    main()
