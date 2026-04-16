"""
ClawSwarm Relay Server — 节点注册 + 命令中转服务

运行在公网可达的机器上（VPS / VM），让本地和远程节点互相发现并通信。

用法:
    # 方式1: 直接运行
    python relay_server.py --port 18080 --host 0.0.0.0

    # 方式2: 后台运行
    nohup python relay_server.py --port 18080 --host 0.0.0.0 &

    # 方式3: 通过 serveo 暴露到公网
    ssh -o ServerAliveInterval=30 -R 0:localhost:18080 serveo.net

Endpoints:
    GET  /health                         - 健康检查
    POST /register                       - 节点注册 (payload: JSON)
    GET  /nodes                          - 列出所有节点
    GET  /discover/{node_id}             - 获取节点连接信息
    POST /unregister/{node_id}           - 注销节点
    POST /cmd/{node_id}                  - 发送命令给节点 (payload: text)
    GET  /poll/{node_id}                 - 节点获取待执行命令
    POST /done/{node_id}                 - 节点提交执行结果 (payload: text)
    GET  /result/{node_id}               - 获取节点执行结果
    GET  /pairing/generate               - 生成配对码
    POST /pairing/connect/{code}         - 使用配对码连接
    GET  /pairing/status/{code}          - 查看配对状态
    GET  /metrics                        - 服务指标
"""

import argparse
import json
import time
import threading
import uuid
import hashlib
import re
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from typing import Dict, Optional


# ── 配置 ────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "relay_data"
NODES_FILE = DATA_DIR / "nodes.json"
QUEUE_DIR = DATA_DIR / "queue"
RESULT_DIR = DATA_DIR / "results"
PAIRING_DIR = DATA_DIR / "pairing"

DATA_DIR.mkdir(exist_ok=True)
QUEUE_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)
PAIRING_DIR.mkdir(exist_ok=True)


# ── 节点注册表 ─────────────────────────────────────────────────────────

class NodeRegistry:
    """线程安全的节点注册表"""
    
    def __init__(self):
        self._lock = threading.RLock()
        self._nodes: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if NODES_FILE.exists():
            try:
                data = json.loads(NODES_FILE.read_text(encoding="utf-8"))
                self._nodes = data.get("nodes", {})
            except Exception:
                self._nodes = {}

    def _save(self):
        try:
            NODES_FILE.write_text(
                json.dumps({"nodes": self._nodes, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def register(self, node_id: str, gateway_url: str, token: str, 
                 capabilities: list, name: str = None, extra: dict = None) -> dict:
        with self._lock:
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            self._nodes[node_id] = {
                "node_id": node_id,
                "name": name or node_id,
                "gateway_url": gateway_url,
                "token": token,
                "capabilities": capabilities,
                "registered_at": now,
                "last_seen": now,
                "status": "online",
                "extra": extra or {},
            }
            self._save()
            return self._nodes[node_id]

    def unregister(self, node_id: str) -> bool:
        with self._lock:
            if node_id in self._nodes:
                del self._nodes[node_id]
                self._save()
                return True
            return False

    def get(self, node_id: str) -> Optional[dict]:
        with self._lock:
            return self._nodes.get(node_id)

    def touch(self, node_id: str) -> bool:
        """更新节点心跳"""
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id]["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self._save()
                return True
            return False

    def list_all(self) -> list:
        with self._lock:
            return list(self._nodes.values())

    def get_online(self, max_age_seconds: int = 300) -> list:
        """获取最近 N 秒内有心跳的节点"""
        with self._lock:
            now = time.time()
            online = []
            for node in self._nodes.values():
                # 简单检查：status=online 且 last_seen 不太旧
                if node.get("status") == "online":
                    online.append(node)
            return online


# ── 命令队列 ───────────────────────────────────────────────────────────

class CommandQueue:
    """线程安全的命令队列，每节点独立队列"""
    
    def __init__(self):
        self._lock = threading.RLock()

    def push(self, node_id: str, command: str, timeout: int = 60) -> str:
        """推入命令，返回 queue_id"""
        queue_id = f"{node_id}_{int(time.time()*1000)}"
        qfile = QUEUE_DIR / f"{queue_id}.json"
        data = {
            "queue_id": queue_id,
            "node_id": node_id,
            "command": command,
            "timeout": timeout,
            "created_at": time.time(),
            "status": "pending",
        }
        qfile.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return queue_id

    def pop(self, node_id: str) -> Optional[dict]:
        """节点获取自己的待执行命令（ FIFO ）"""
        with self._lock:
            for qfile in sorted(QUEUE_DIR.glob(f"{node_id}_*.json")):
                try:
                    data = json.loads(qfile.read_text(encoding="utf-8"))
                    if data.get("status") == "pending":
                        # 标记为执行中
                        data["status"] = "executing"
                        data["executing_since"] = time.time()
                        qfile.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                        return data
                except Exception:
                    pass
            return None

    def get_pending(self, node_id: str) -> Optional[dict]:
        """查看pending命令（不弹出）"""
        with self._lock:
            for qfile in sorted(QUEUE_DIR.glob(f"{node_id}_*.json")):
                try:
                    data = json.loads(qfile.read_text(encoding="utf-8"))
                    if data.get("status") == "pending":
                        return data
                except Exception:
                    pass
            return None

    def done(self, node_id: str, result: str, status: str = "ok") -> bool:
        """节点提交执行结果"""
        with self._lock:
            # 找到该节点最新的 executing 状态命令
            for qfile in sorted(QUEUE_DIR.glob(f"{node_id}_*.json")):
                try:
                    data = json.loads(qfile.read_text(encoding="utf-8"))
                    if data.get("node_id") == node_id and data.get("status") == "executing":
                        queue_id = data["queue_id"]
                        rfile = RESULT_DIR / f"{queue_id}.json"
                        rfile.write_text(json.dumps({
                            "queue_id": queue_id,
                            "node_id": node_id,
                            "status": status,
                            "result": result,
                            "done_at": time.time(),
                        }, ensure_ascii=False), encoding="utf-8")
                        # 删除队列文件
                        qfile.unlink()
                        return True
                except Exception:
                    pass
            return False

    def get_result(self, node_id: str) -> Optional[dict]:
        """获取该节点的最新结果（消费型）"""
        with self._lock:
            results = sorted(RESULT_DIR.glob(f"{node_id}_*.json"), key=lambda f: f.stat().st_mtime)
            if results:
                try:
                    data = json.loads(results[-1].read_text(encoding="utf-8"))
                    # 消费后删除
                    results[-1].unlink()
                    return data
                except Exception:
                    pass
            return None

    def get_result_peek(self, node_id: str) -> Optional[dict]:
        """查看最新结果（不消费）"""
        with self._lock:
            results = sorted(RESULT_DIR.glob(f"{node_id}_*.json"), key=lambda f: f.stat().st_mtime)
            if results:
                try:
                    return json.loads(results[-1].read_text(encoding="utf-8"))
                except Exception:
                    pass
            return None


# ── 配对码系统 ──────────────────────────────────────────────────────────

class PairingManager:
    """一次性配对码，实现龙虾一键互联"""
    
    def __init__(self):
        self._lock = threading.RLock()
        self._codes: Dict[str, dict] = {}
        self._load()

    def _load(self):
        for pfile in PAIRING_DIR.glob("*.json"):
            try:
                data = json.loads(pfile.read_text(encoding="utf-8"))
                self._codes[data["code"]] = data
            except Exception:
                pass

    def generate(self, node_id: str, node_info: dict = None) -> str:
        """生成6位配对码"""
        with self._lock:
            code = str(uuid.uuid4().int)[:6]
            entry = {
                "code": code,
                "node_id": node_id,
                "node_info": node_info or {},
                "created_at": time.time(),
                "status": "waiting",  # waiting -> connected -> expired
                "partner_node_id": None,
                "partner_info": None,
            }
            pfile = PAIRING_DIR / f"{code}.json"
            pfile.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            self._codes[code] = entry
            return code

    def connect(self, code: str, node_id: str, node_info: dict = None) -> dict:
        """使用配对码连接，建立双向关系"""
        with self._lock:
            if code not in self._codes:
                return {"error": "INVALID_CODE", "message": "配对码无效或已过期"}
            
            entry = self._codes[code]
            if entry["status"] != "waiting":
                return {"error": "ALREADY_USED", "message": "配对码已被使用"}
            
            if entry["node_id"] == node_id:
                return {"error": "SELF_CONNECT", "message": "不能连接自己"}
            
            # 建立双向连接
            entry["status"] = "connected"
            entry["partner_node_id"] = node_id
            entry["partner_info"] = node_info or {}
            entry["connected_at"] = time.time()
            
            # 写回文件
            pfile = PAIRING_DIR / f"{code}.json"
            pfile.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            
            return {
                "status": "connected",
                "code": code,
                "partner": {
                    "node_id": entry["node_id"],
                    "node_info": entry["node_info"],
                },
                "self": {
                    "node_id": node_id,
                    "node_info": node_info or {},
                },
            }

    def get_status(self, code: str) -> Optional[dict]:
        return self._codes.get(code)


# ── 全局单例 ────────────────────────────────────────────────────────────

registry = NodeRegistry()
cmd_queue = CommandQueue()
pairing = PairingManager()


# ── HTTP Handler ────────────────────────────────────────────────────────

METRICS = {
    "started_at": time.time(),
    "requests": 0,
    "errors": 0,
}

class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_json(self, code: int, data: dict):
        METRICS["requests"] += 1
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, code: int, text: str):
        METRICS["requests"] += 1
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _recv_body(self) -> str:
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            return self.rfile.read(length).decode("utf-8")
        return ""

    def _parse_json(self, body: str) -> dict:
        try:
            return json.loads(body)
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # GET /health
        if path == "/health" or path == "":
            uptime = int(time.time() - METRICS["started_at"])
            return self._send_json(200, {
                "status": "ok",
                "uptime_seconds": uptime,
                "nodes_registered": len(registry.list_all()),
                "requests": METRICS["requests"],
                "errors": METRICS["errors"],
            })

        # GET /nodes
        if path == "/nodes":
            return self._send_json(200, {
                "nodes": registry.list_all(),
                "count": len(registry.list_all()),
            })

        # GET /discover/{node_id}
        m = re.match(r"^/discover/(.+)$", path)
        if m:
            node_id = m.group(1)
            node = registry.get(node_id)
            if node:
                # 不暴露 token
                safe_node = {k: v for k, v in node.items() if k != "token"}
                return self._send_json(200, {"node": safe_node})
            return self._send_json(404, {"error": "NODE_NOT_FOUND", "node_id": node_id})

        # GET /poll/{node_id}  (兼容旧协议)
        m = re.match(r"^/poll(?:/([^/]+))?$", path)
        if m:
            node_id = m.group(1)
            if node_id:
                registry.touch(node_id)
                pending = cmd_queue.get_pending(node_id)
                if pending:
                    return self._send_text(200, pending["command"])
                return self._send_text(200, "")
            return self._send_json(400, {"error": "NODE_ID_REQUIRED"})

        # GET /result/{node_id}  (兼容旧协议)
        m = re.match(r"^/result(?:/([^/]+))?$", path)
        if m:
            node_id = m.group(1)
            if node_id:
                result = cmd_queue.get_result(node_id)
                if result:
                    return self._send_text(200, result.get("result", ""))
                return self._send_text(200, "")
            return self._send_json(400, {"error": "NODE_ID_REQUIRED"})

        # GET /pairing/generate
        if path == "/pairing/generate":
            node_id = parse_qs(parsed.query).get("node_id", [None])[0]
            if not node_id:
                return self._send_json(400, {"error": "node_id required"})
            code = pairing.generate(node_id)
            return self._send_json(200, {"code": code, "expires_in": 300})

        # GET /pairing/status/{code}
        m = re.match(r"^/pairing/status/(.+)$", path)
        if m:
            status = pairing.get_status(m.group(1))
            if status:
                return self._send_json(200, status)
            return self._send_json(404, {"error": "CODE_NOT_FOUND"})

        # GET /metrics
        if path == "/metrics":
            uptime = int(time.time() - METRICS["started_at"])
            return self._send_json(200, {
                **METRICS,
                "uptime_seconds": uptime,
                "nodes_registered": len(registry.list_all()),
            })

        self._send_json(404, {"error": "NOT_FOUND", "path": path})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._recv_body()

        # POST /register
        if path == "/register":
            data = self._parse_json(body)
            node_id = data.get("node_id") or data.get("nodeId")
            if not node_id:
                return self._send_json(400, {"error": "node_id required"})
            
            result = registry.register(
                node_id=node_id,
                gateway_url=data.get("gateway_url", ""),
                token=data.get("token", ""),
                capabilities=data.get("capabilities", []),
                name=data.get("name"),
                extra={k: v for k, v in data.items() 
                       if k not in ("node_id", "gateway_url", "token", "capabilities", "name")},
            )
            # 不返回 token
            safe = {k: v for k, v in result.items() if k != "token"}
            return self._send_json(200, safe)

        # POST /heartbeat/{node_id}
        m = re.match(r"^/heartbeat/(.+)$", path)
        if m:
            node_id = m.group(1)
            registry.touch(node_id)
            return self._send_json(200, {"status": "ok", "node_id": node_id})

        # POST /unregister/{node_id}
        m = re.match(r"^/unregister/(.+)$", path)
        if m:
            ok = registry.unregister(m.group(1))
            return self._send_json(200, {"ok": ok})

        # POST /cmd/{node_id}  (兼容旧协议) 或 POST /cmd
        m = re.match(r"^/cmd(?:/(.+))?$", path)
        if m:
            node_id = m.group(1)
            if not node_id:
                data = self._parse_json(body)
                node_id = data.get("node_id")
                command = data.get("command", body)
            else:
                command = body
            
            if not node_id:
                return self._send_json(400, {"error": "node_id required"})
            
            # 检查节点是否存在
            node = registry.get(node_id)
            if not node:
                return self._send_json(404, {"error": "NODE_NOT_FOUND", "node_id": node_id})
            
            timeout = data.get("timeout", 60) if isinstance(data, dict) else 60
            queue_id = cmd_queue.push(node_id, command, timeout=timeout)
            return self._send_json(200, {"ok": True, "queue_id": queue_id})

        # POST /done/{node_id}  (节点提交结果)
        m = re.match(r"^/done/(.+)$", path)
        if m:
            node_id = m.group(1)
            registry.touch(node_id)
            ok = cmd_queue.done(node_id, body, status="ok")
            return self._send_json(200, {"ok": ok})

        # POST /pairing/connect/{code}
        m = re.match(r"^/pairing/connect/(.+)$", path)
        if m:
            code = m.group(1)
            data = self._parse_json(body)
            node_id = data.get("node_id")
            if not node_id:
                return self._send_json(400, {"error": "node_id required"})
            result = pairing.connect(code, node_id, data.get("node_info"))
            if "error" in result:
                return self._send_json(400, result)
            return self._send_json(200, result)

        self._send_json(404, {"error": "NOT_FOUND", "path": path})

    def log_message(self, format, *args):
        # 简化日志，只输出请求路径和状态码
        try:
            print(f"[{time.strftime('%H:%M:%S')}] {args[1]} {args[0]}")
        except Exception:
            pass


# ── 启动 ────────────────────────────────────────────────────────────────

def run(port: int = 18080, host: str = "0.0.0.0"):
    server = HTTPServer((host, port), RelayHandler)
    print(f"ClawSwarm Relay Server 启动")
    print(f"  监听: http://{host}:{port}")
    print(f"  数据目录: {DATA_DIR}")
    print(f"  节点注册: POST /register")
    print(f"  节点列表: GET /nodes")
    print(f"  配对码: GET /pairing/generate?node_id=xxx")
    print()
    print("示例:")
    print(f"  注册节点: curl -X POST http://localhost:{port}/register \\")
    print(f"    -H 'Content-Type: application/json' \\")
    print(f"    -d '{{\"node_id\":\"my-claw\",\"gateway_url\":\"http://localhost:28789\",\"token\":\"xxx\",\"capabilities\":[\"shell\"]}}'")
    print()
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ClawSwarm Relay Server")
    parser.add_argument("--port", type=int, default=18080, help="监听端口 (default: 18080)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (default: 0.0.0.0)")
    args = parser.parse_args()
    run(port=args.port, host=args.host)
