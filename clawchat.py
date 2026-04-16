"""
ClawChat - ClawSwarm Agent间聊天模块
=======================================
提供实时消息推送 + 持久化存储 + 跨公网 relay 桥接。

架构:
    本地 WebSocket 客户端 ←→ clawchat server (port 5002)
                                   ↓
                          SQLite 消息存储
                                   ↓
                          远程 relay 桥接 ←→ KimiClaw 等远程节点

用法:
    # 启动服务器
    python clawchat.py

    # 发送消息
    from clawchat import ClawChatClient
    client = ClawChatClient("http://localhost:5002", agent_id="main-agent")
    client.send("kimi-claw-01", "帮我查一下服务器状态")

    # WebSocket 实时收消息
    client.start_listener(lambda msg: print(f"收到: {msg}"))
"""

import asyncio
import json
import sqlite3
import ssl
import sys
import threading
import time
import traceback
import uuid
import urllib.request
import urllib.error
import weakref
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, List, Any
from concurrent.futures import ThreadPoolExecutor

# ── 内部导入，跳过 skill ──────────────────────────────────────────────
try:
    from . import paths
    BASE_DIR = paths.BASE_DIR
except ImportError:
    BASE_DIR = Path(__file__).parent / "swarm_data"


# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ChatMessage:
    """聊天消息"""
    id: str                    # 唯一 ID
    from_agent: str            # 发送方
    to_agent: str              # 接收方
    content: str               # 内容
    msg_type: str = "text"     # text | command | result | system
    status: str = "pending"    # pending | delivered | read
    created_at: str = ""       # ISO timestamp
    delivered_at: str = ""    # 送达时间
    read_at: str = ""          # 已读时间
    relay_url: str = ""        # 来自哪个 relay（跨公网时）
    thread_id: str = ""        # 会话线程 ID

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════
# SQLite 持久存储
# ═══════════════════════════════════════════════════════════════════════

class ChatStore:
    """SQLite-backed 消息存储"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = BASE_DIR / "clawchat" / "messages.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id          TEXT PRIMARY KEY,
                    from_agent  TEXT NOT NULL,
                    to_agent    TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    msg_type    TEXT DEFAULT 'text',
                    status      TEXT DEFAULT 'pending',
                    created_at  TEXT NOT NULL,
                    delivered_at TEXT DEFAULT '',
                    read_at     TEXT DEFAULT '',
                    relay_url   TEXT DEFAULT '',
                    thread_id   TEXT DEFAULT ''
                )
            """)
            # 索引加速查询
            conn.execute("CREATE INDEX IF NOT EXISTS idx_from ON messages(from_agent)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_to ON messages(to_agent)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON messages(created_at)")
            conn.commit()
            conn.close()

    def save(self, msg: ChatMessage) -> ChatMessage:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute("""
                INSERT OR REPLACE INTO messages
                (id, from_agent, to_agent, content, msg_type, status,
                 created_at, delivered_at, read_at, relay_url, thread_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg.id, msg.from_agent, msg.to_agent, msg.content, msg.msg_type,
                msg.status, msg.created_at, msg.delivered_at, msg.read_at,
                msg.relay_url, ""
            ))
            conn.commit()
            conn.close()
        return msg

    # 显式列顺序，避免 SELECT * 顺序不确定问题
    _COLS = "id,from_agent,to_agent,content,msg_type,status,created_at,delivered_at,read_at,relay_url,thread_id"

    def get(self, msg_id: str) -> Optional[ChatMessage]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            row = conn.execute(
                f"SELECT {self._COLS} FROM messages WHERE id=?", (msg_id,)
            ).fetchone()
            conn.close()
        if row:
            return ChatMessage(*row)
        return None

    def get_conversation(self, agent_a: str, agent_b: str, limit: int = 50) -> List[ChatMessage]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            rows = conn.execute(f"""
                SELECT {self._COLS} FROM messages
                WHERE (from_agent=? AND to_agent=?) OR (from_agent=? AND to_agent=?)
                ORDER BY created_at DESC LIMIT ?
            """, (agent_a, agent_b, agent_b, agent_a, limit)).fetchall()
            conn.close()
        return [ChatMessage(*row) for row in reversed(rows)]

    def get_inbox(self, agent_id: str, unread_only: bool = False) -> List[ChatMessage]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            query = f"SELECT {self._COLS} FROM messages WHERE to_agent=? "
            if unread_only:
                query += "AND status != 'read' "
            query += "ORDER BY created_at DESC LIMIT 100"
            rows = conn.execute(query, (agent_id,)).fetchall()
            conn.close()
        return [ChatMessage(*row) for row in reversed(rows)]

    def mark_read(self, msg_id: str):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute(
                "UPDATE messages SET status='read', read_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), msg_id)
            )
            conn.commit()
            conn.close()

    def mark_delivered(self, msg_id: str):
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute(
                "UPDATE messages SET status='delivered', delivered_at=? WHERE id=?",
                (ts, msg_id)
            )
            conn.commit()
            conn.close()

    def get_partners(self, agent_id: str) -> List[dict]:
        """获取与 agent_id 有过对话的所有其他 agent"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            rows = conn.execute("""
                SELECT DISTINCT
                    CASE
                        WHEN from_agent=? THEN to_agent
                        ELSE from_agent
                    END as partner,
                    MAX(created_at) as last_time
                FROM messages
                WHERE from_agent=? OR to_agent=?
                GROUP BY partner
                ORDER BY last_time DESC
            """, (agent_id, agent_id, agent_id)).fetchall()
        result = []
        for partner, last_time in rows:
            unread_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE to_agent=? AND from_agent=? AND status!='read'",
                (agent_id, partner)
            ).fetchone()[0]
            result.append({"partner": partner, "last_time": last_time, "unread": unread_count})
        conn.close()
        return result

    def search(self, agent_id: str, query: str, limit: int = 20) -> List[ChatMessage]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            rows = conn.execute(f"""
                SELECT {self._COLS} FROM messages
                WHERE (from_agent=? OR to_agent=?) AND content LIKE ?
                ORDER BY created_at DESC LIMIT ?
            """, (agent_id, agent_id, f"%{query}%", limit)).fetchall()
            conn.close()
        return [ChatMessage(*row) for row in reversed(rows)]


# ═══════════════════════════════════════════════════════════════════════
# Relay 桥接器（跨公网消息同步）
# ═══════════════════════════════════════════════════════════════════════

class RelayBridge:
    """
    将本地 clawchat 与远程 relay 连接起来。
    - 拉取远程消息 → 存入本地 store → WebSocket 推送
    - 发送本地消息 → 路由到 relay（或直接 WebSocket）
    """

    def __init__(self, store: ChatStore, local_agent_id: str, on_message: Callable[[ChatMessage], None]):
        self.store = store
        self.local_agent_id = local_agent_id
        self.on_message = on_message  # 外部注册的回调（WebSocket推送等）
        self._ctx = ssl.create_default_context()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._relay_configs: List[dict] = []
        self._known_remote_ids: set = set()  # 避免重复处理

    def add_relay(self, relay_url: str, agent_id: str, capabilities: List[str] = None):
        """添加一个远程 relay"""
        self._relay_configs.append({
            "relay_url": relay_url.rstrip("/"),
            "agent_id": agent_id,
            "capabilities": capabilities or ["exec", "fetch"],
        })

    def start(self, poll_interval: float = 3.0):
        """启动桥接线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, args=(poll_interval,), daemon=True)
        self._thread.start()
        print(f"[clawchat] RelayBridge started for {self.local_agent_id}, polling {poll_interval}s")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self, interval: float):
        while self._running:
            for cfg in self._relay_configs:
                self._poll_relay(cfg)
            time.sleep(interval)

    def _poll_relay(self, cfg: dict):
        """从 relay 拉取消息"""
        relay_url = cfg["relay_url"]
        agent_id = cfg["agent_id"]
        try:
            url = f"{relay_url}/inbox/{agent_id}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, context=self._ctx, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))

            messages = data.get("messages", [])
            if not messages:
                return

            for raw in messages:
                msg_id = raw.get("id", "")
                if msg_id in self._known_remote_ids:
                    continue
                self._known_remote_ids.add(msg_id)

                # 构建 ChatMessage
                msg = ChatMessage(
                    id=msg_id,
                    from_agent=raw.get("from", raw.get("from_agent", "unknown")),
                    to_agent=agent_id,
                    content=raw.get("content", raw.get("text", "")),
                    msg_type=raw.get("type", "text"),
                    status="delivered",
                    created_at=raw.get("timestamp", raw.get("created_at", "")),
                    relay_url=relay_url,
                )
                # 存本地
                self.store.save(msg)
                # 触发推送
                self.on_message(msg)

        except Exception as ex:
            # 静默失败，避免日志刷屏
            pass

    def send_via_relay(self, target_agent: str, content: str, relay_url: str,
                       from_agent: str, msg_type: str = "text") -> Optional[ChatMessage]:
        """通过 relay 发送消息到远程 agent"""
        msg_id = f"local_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
        msg = ChatMessage(
            id=msg_id,
            from_agent=from_agent,
            to_agent=target_agent,
            content=content,
            msg_type=msg_type,
            status="pending",
            relay_url=relay_url,
        )

        try:
            body = json.dumps({
                "id": msg_id,
                "content": content,
                "type": msg_type,
                "from": from_agent,
                "timestamp": msg.created_at,
            }).encode("utf-8")
            url = f"{relay_url}/msg/{from_agent}/{target_agent}"
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, context=self._ctx, timeout=10) as r:
                result = json.loads(r.read().decode("utf-8"))

            if result.get("ok", False):
                msg.status = "delivered"
                self.store.save(msg)
                return msg
            else:
                self.store.save(msg)
                return msg

        except Exception as ex:
            msg.status = "failed"
            self.store.save(msg)
            return msg


# ═══════════════════════════════════════════════════════════════════════
# WebSocket 管理器（实时推送）
# ═══════════════════════════════════════════════════════════════════════

class WSManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self._clients: List[Any] = []  # {(agent_id, websocket): True}
        self._lock = threading.Lock()

    def register(self, agent_id: str, ws):
        with self._lock:
            self._clients.append((agent_id, ws))
        print(f"[clawchat] WebSocket registered: {agent_id}, total={len(self._clients)}")

    def unregister(self, ws):
        with self._lock:
            self._clients = [(a, w) for a, w in self._clients if w != ws]

    def push(self, agent_id: str, payload: dict):
        """推送消息到指定 agent 的所有连接"""
        msg = json.dumps(payload, ensure_ascii=False)
        dead = []
        with self._lock:
            for a, ws in self._clients:
                if a == agent_id or a == "*":
                    try:
                        ws.write_message(msg)
                    except Exception:
                        dead.append((a, ws))
            for item in dead:
                self._clients.remove(item)

    def broadcast(self, payload: dict):
        self.push("*", payload)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._clients)


# ═══════════════════════════════════════════════════════════════════════
# HTTP Server（FastAPI 风格，手写）
# ═══════════════════════════════════════════════════════════════════════

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
    from fastapi.responses import JSONResponse
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    print("[clawchat] FastAPI not available, HTTP API disabled")

import asyncio as aio


class ClawChatServer:
    """
    ClawChat HTTP + WebSocket 服务器。
    集成到现有 dashboard，或者独立运行在 port 5002。
    """

    def __init__(self, local_agent_id: str = "main-agent",
                 port: int = 5002,
                 relay_configs: List[dict] = None):
        if not HAS_FASTAPI:
            raise RuntimeError("FastAPI required: pip install fastapi uvicorn websockets")

        self.local_agent_id = local_agent_id
        self.port = port
        self.store = ChatStore()
        self.ws_manager = WSManager()
        self.bridge = RelayBridge(
            self.store, local_agent_id,
            on_message=self._on_remote_message
        )
        if relay_configs:
            for cfg in relay_configs:
                self.bridge.add_relay(cfg["relay_url"], cfg["agent_id"])

        self.app = FastAPI(title="ClawChat API", version="1.0.0")

        @self.app.get("/")
        async def root():
            return {"service": "clawchat", "agent": self.local_agent_id, "ws_clients": self.ws_manager.count}

        @self.app.get("/health")
        async def health():
            return {"status": "ok", "agent": self.local_agent_id}

        @self.app.get("/inbox/{agent_id}")
        async def get_inbox(agent_id: str, unread_only: bool = False):
            messages = self.store.get_inbox(agent_id, unread_only=unread_only)
            return {"agent_id": agent_id, "messages": [m.to_dict() for m in messages], "count": len(messages)}

        @self.app.get("/conversation/{agent_a}/{agent_b}")
        async def get_conversation(agent_a: str, agent_b: str, limit: int = 50):
            messages = self.store.get_conversation(agent_a, agent_b, limit=limit)
            return {"messages": [m.to_dict() for m in messages], "count": len(messages)}

        @self.app.get("/partners/{agent_id}")
        async def get_partners(agent_id: str):
            return {"partners": self.store.get_partners(agent_id)}

        @self.app.post("/send/{from_agent}/{to_agent}")
        async def send_message(from_agent: str, to_agent: str, request: dict):
            content = request.get("content", "")
            msg_type = request.get("type", "text")
            if not content:
                raise HTTPException(status_code=400, detail="content required")

            msg = self._create_message(from_agent, to_agent, content, msg_type)
            self.store.save(msg)
            # 本地推送
            self.ws_manager.push(to_agent, {"event": "message", "data": msg.to_dict()})
            return {"ok": True, "message": msg.to_dict()}

        @self.app.post("/read/{msg_id}")
        async def mark_read(msg_id: str):
            self.store.mark_read(msg_id)
            msg = self.store.get(msg_id)
            if msg:
                self.ws_manager.push(msg.from_agent, {"event": "read", "data": {"msg_id": msg_id}})
            return {"ok": True}

        @self.app.websocket("/ws/{agent_id}")
        async def websocket_endpoint(websocket: WebSocket, agent_id: str):
            await websocket.accept()
            self.ws_manager.register(agent_id, websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    try:
                        payload = json.loads(data)
                        # 处理客户端消息
                        await self._handle_ws_message(agent_id, payload, websocket)
                    except json.JSONDecodeError:
                        await websocket.send_json({"error": "invalid JSON"})
            except WebSocketDisconnect:
                self.ws_manager.unregister(websocket)
            except Exception:
                self.ws_manager.unregister(websocket)

    def _create_message(self, from_agent: str, to_agent: str, content: str,
                        msg_type: str = "text") -> ChatMessage:
        return ChatMessage(
            id=f"m_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}",
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            msg_type=msg_type,
            status="pending",
        )

    async def _handle_ws_message(self, agent_id: str, payload: dict, ws):
        """处理 WebSocket 客户端发来的消息"""
        action = payload.get("action")
        if action == "send":
            msg = self._create_message(
                payload.get("from", agent_id),
                payload.get("to", ""),
                payload.get("content", ""),
                payload.get("type", "text"),
            )
            self.store.save(msg)
            # 推送给目标
            self.ws_manager.push(msg.to_agent, {"event": "message", "data": msg.to_dict()})
            await ws.send_json({"event": "sent", "data": msg.to_dict()})
        elif action == "ping":
            await ws.send_json({"event": "pong", "agent": self.local_agent_id})

    def _on_remote_message(self, msg: ChatMessage):
        """RelayBridge 收到远程消息 → WebSocket 推送"""
        self.ws_manager.push(msg.to_agent, {"event": "message", "data": msg.to_dict()})

    def start(self, background: bool = True):
        """启动服务器"""
        self.bridge.start(poll_interval=3.0)
        if background:
            t = threading.Thread(target=self._run_server, daemon=True)
            t.start()
            print(f"[clawchat] Server starting on port {self.port}")
        else:
            uvicorn.run(self.app, host="0.0.0.0", port=self.port, log_level="warning")

    def _run_server(self):
        uvicorn.run(self.app, host="0.0.0.0", port=self.port,
                    log_level="warning", access_log=False)

    def stop(self):
        self.bridge.stop()


# ═══════════════════════════════════════════════════════════════════════
# 轻量级客户端（不需要 FastAPI，标准库即可）
# ═══════════════════════════════════════════════════════════════════════

class ClawChatClient:
    """
    ClawChat 客户端（本地 agent 使用）。
    支持 HTTP REST + WebSocket 实时监听。
    """

    def __init__(self, server_url: str = "http://localhost:5002",
                 agent_id: str = "unknown",
                 relay_url: str = ""):
        self.server_url = server_url.rstrip("/")
        self.agent_id = agent_id
        self.relay_url = relay_url
        self._ctx = ssl.create_default_context()
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._running = False
        self._listeners: List[Callable[[dict], None]] = []

    def _http(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self.server_url}{path}"
        if method == "GET":
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
        else:
            body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8") if data else b""
            req = urllib.request.Request(
                url, data=body, method=method,
                headers={"Content-Type": "application/json", "Accept": "application/json"}
            )
        with urllib.request.urlopen(req, context=self._ctx, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def send(self, to_agent: str, content: str, msg_type: str = "text") -> dict:
        """发送消息"""
        result = self._http("POST", f"/send/{self.agent_id}/{to_agent}", {
            "content": content, "type": msg_type
        })
        return result

    def inbox(self, unread_only: bool = False) -> List[dict]:
        """获取收件箱"""
        r = self._http("GET", f"/inbox/{self.agent_id}?unread_only={str(unread_only).lower()}")
        return r.get("messages", [])

    def conversation(self, partner: str, limit: int = 50) -> List[dict]:
        """获取与某 agent 的对话历史"""
        r = self._http("GET", f"/conversation/{self.agent_id}/{partner}?limit={limit}")
        return r.get("messages", [])

    def partners(self) -> List[dict]:
        """获取所有对话对象"""
        r = self._http("GET", f"/partners/{self.agent_id}")
        return r.get("partners", [])

    def mark_read(self, msg_id: str):
        return self._http("POST", f"/read/{msg_id}")

    def start_listener(self, callback: Callable[[dict], None]):
        """启动 WebSocket 监听（后台线程）"""
        self._listeners.append(callback)
        if not self._running:
            self._running = True
            self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
            self._ws_thread.start()

    def _ws_loop(self):
        ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        while self._running:
            try:
                import websocket
                self._ws = websocket.create_connection(
                    f"{ws_url}/ws/{self.agent_id}",
                    timeout=30
                )
                print(f"[clawchat] WebSocket connected as {self.agent_id}")
                while self._running:
                    try:
                        data = self._ws.recv()
                        payload = json.loads(data)
                        for cb in self._listeners:
                            try:
                                cb(payload)
                            except Exception:
                                pass
                    except Exception:
                        break
                self._ws.close()
            except ImportError:
                # 没有 websocket 库，降级为轮询
                print("[clawchat] websocket-client not installed, falling back to polling")
                self._poll_loop()
                break
            except Exception as ex:
                print(f"[clawchat] WebSocket error: {ex}, retrying in 5s...")
                time.sleep(5)

    def _poll_loop(self):
        """轮询降级（无 websocket 库时）"""
        while self._running:
            try:
                msgs = self.inbox(unread_only=True)
                for msg in msgs:
                    for cb in self._listeners:
                        try:
                            cb({"event": "message", "data": msg})
                        except Exception:
                            pass
                    self.mark_read(msg["id"])
            except Exception:
                pass
            time.sleep(3)

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.close()

    def health(self) -> dict:
        try:
            return self._http("GET", "/health")
        except Exception:
            return {"status": "error"}


# ═══════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ClawChat - Agent间聊天")
    parser.add_argument("--port", type=int, default=5002, help="服务器端口")
    parser.add_argument("--agent", default="main-agent", help="本地 agent ID")
    parser.add_argument("--relay", action="append", help="远程 relay URL（可多次指定）")
    args = parser.parse_args()

    relay_configs = []
    if args.relay:
        import re
        for r in args.relay:
            m = re.match(r"(.+)/(.+)", r)
            if m:
                relay_configs.append({"relay_url": m.group(1), "agent_id": m.group(2)})
            else:
                print(f"[clawchat] Invalid relay format: {r}, expected URL/agent_id")

    server = ClawChatServer(
        local_agent_id=args.agent,
        port=args.port,
        relay_configs=relay_configs,
    )
    server.start(background=False)


if __name__ == "__main__":
    main()
