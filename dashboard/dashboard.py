"""
ClawSwarm Dashboard — Web UI 监控面板
基于 FastAPI + WebSocket，实时展示龙虾集群状态、任务 DAG、执行结果

运行:
    python dashboard/dashboard.py [--port 5000] [--host 0.0.0.0]
    或: uvicorn dashboard.dashboard:app --host 0.0.0.0 --port 5000 --reload
"""

import asyncio
import json
import os
import sys
import time
import threading
from pathlib import Path

# ClawSwarm 根目录（用于 subprocess 调用）
_CLAWSWARM_ROOT = str(Path(__file__).parent.parent.resolve())
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route, WebSocketRoute

# ── 项目路径 ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

# ── 尝试导入 ClawSwarm 组件 ─────────────────────────────────────────────
from contextlib import asynccontextmanager

try:
    from monitor import MonitorService, get_monitor
    from models import TaskStatus
    HAS_CLAWSWARM = True
except ImportError:
    HAS_CLAWSWARM = False
    print("[Dashboard] ClawSwarm modules not found, running in demo mode")

# ── Relay 客户端 ───────────────────────────────────────────────────────
RELAY_URL = os.environ.get("RELAY_URL", "http://localhost:18080")
RELAY_NODE_ID = os.environ.get("RELAY_NODE_ID", "dashboard")
RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "dashboard-token")
HAS_RELAY = False

try:
    from relay_client import RelayClient, RemoteNodeManager
    _relay_client = None  # lazy init
    _node_manager = None
    HAS_RELAY = True
    print(f"[Dashboard] Relay 客户端已加载，relay: {RELAY_URL}")
except ImportError:
    HAS_RELAY = False
    print("[Dashboard] Relay 客户端未找到，节点管理功能不可用")

def get_relay_client():
    """懒加载 RelayClient 单例"""
    global _relay_client
    if _relay_client is None and HAS_RELAY:
        _relay_client = RelayClient(
            relay_url=RELAY_URL,
            node_id=RELAY_NODE_ID,
            gateway_url="http://localhost:28789",
            token=RELAY_TOKEN,
            capabilities=["dashboard", "monitor"],
        )
    return _relay_client

def get_node_manager():
    """懒加载 RemoteNodeManager 单例"""
    global _node_manager
    if _node_manager is None and HAS_RELAY:
        _node_manager = RemoteNodeManager()
    return _node_manager


# ── Lifespan（必须放在 app = FastAPI 之前）──────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_collect_events())
    yield

# ── FastAPI App ─────────────────────────────────────────────────────────

app = FastAPI(
    title="ClawSwarm Dashboard",
    description="🦞 一只龙虾指挥另一只龙虾 — Web 监控面板",
    version="0.7.0",
    lifespan=lifespan,
)


# ── WebSocket 连接管理器 ─────────────────────────────────────────────────

class ConnectionManager:
    """管理所有 WebSocket 连接"""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        await self._send_initial_state(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self._connections.discard(websocket)

    async def _send_initial_state(self, websocket: WebSocket):
        """发送初始状态"""
        state = await self._collect_full_state()
        try:
            await websocket.send_json({
                "type": "init",
                "data": state,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception:
            pass

    async def broadcast(self, event: dict):
        """广播事件到所有连接"""
        async with self._lock:
            dead = set()
            for ws in self._connections:
                try:
                    await ws.send_json(event)
                except Exception:
                    dead.add(ws)
            self._connections -= dead

    async def _collect_full_state(self) -> dict:
        """收集完整状态供新连接使用"""
        state = {
            "monitor": {"status": "unavailable"},
            "nodes": [],
            "tasks": _task_history.get("tasks", []),
            "events": _event_log.get("events", [])[-50:],
            "swarm": _swarm_state,
        }

        if HAS_CLAWSWARM:
            try:
                monitor = get_monitor()
                state["monitor"] = monitor.get_status()
            except Exception:
                pass

        return state


manager = ConnectionManager()


# ── 全局状态（简化版，不需要完整的 ClawSwarm 也可运行）──────────────

_task_history: Dict[str, List[dict]] = {"tasks": []}
_event_log: Dict[str, List[dict]] = {"events": []}

_swarm_state = {
    "initialized": HAS_CLAWSWARM,
    "version": "0.7.0",
    "mode": "demo" if not HAS_CLAWSWARM else "live",
    "start_time": datetime.now().isoformat(),
}


# ── 后台事件收集器 ─────────────────────────────────────────────────────

async def _collect_events():
    """定期收集事件并广播"""
    last_status = {}
    while True:
        await asyncio.sleep(3)

        event = {"type": "ping", "timestamp": datetime.now().isoformat()}

        if HAS_CLAWSWARM:
            try:
                monitor = get_monitor()
                status = monitor.get_status()

                # 检测节点状态变化
                for node in status.get("nodes", {}).get("list", []):
                    nid = node["node_id"]
                    prev = last_status.get(nid)
                    if prev and prev.get("status") != node["status"]:
                        await manager.broadcast({
                            "type": "node_status_change",
                            "node_id": nid,
                            "old": prev["status"],
                            "new": node["status"],
                            "timestamp": datetime.now().isoformat(),
                        })
                    last_status[nid] = node

                event["data"] = {"monitor": status}
            except Exception:
                pass

        await manager.broadcast(event)


# ── REST API ─────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    """获取集群整体状态"""
    state = _swarm_state.copy()
    if HAS_CLAWSWARM:
        try:
            monitor = get_monitor()
            state["monitor"] = monitor.get_status()
        except Exception:
            state["monitor"] = {"error": str(Exception)}
    else:
        state["monitor"] = {"status": "demo mode"}
    return state


@app.get("/api/nodes")
async def get_nodes():
    """获取节点列表（从 Monitor + Hub 合并）"""
    nodes = []
    
    # 从 Monitor 获取本地节点
    if HAS_CLAWSWARM:
        try:
            monitor = get_monitor()
            status = monitor.get_status()
            monitor_nodes = status.get("nodes", {}).get("list", [])
            nodes.extend(monitor_nodes)
        except Exception as e:
            print(f"[Dashboard] Monitor error: {e}")
    
    # 从 Hub 获取远程 agents
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:18080/hub/agents", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    hub_data = await resp.json()
                    for agent in hub_data.get("agents", []):
                        agent_id = agent.get("agent_id") if isinstance(agent, dict) else agent
                        if not agent_id:
                            continue
                        # 检查是否已存在
                        if not any(n.get("node_id") == agent_id for n in nodes):
                            nodes.append({
                                "node_id": agent_id,
                                "status": "online" if agent.get("idle", True) else "busy",
                                "capabilities": agent.get("capabilities", ["fetch", "exec", "python"]),
                                "cpu": 0.0,
                                "memory": 0.0,
                                "source": "hub"
                            })
    except Exception as e:
        print(f"[Dashboard] Hub fetch error: {e}")
    
    return {"total": len(nodes), "online": len([n for n in nodes if n.get("status") == "online"]), "list": nodes}


@app.get("/api/tasks")
async def get_tasks(limit: int = Query(50, ge=1, le=200)):
    """获取任务历史"""
    tasks = _task_history.get("tasks", [])
    return {"total": len(tasks), "tasks": tasks[-limit:]}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """获取特定任务"""
    tasks = _task_history.get("tasks", [])
    for t in tasks:
        if t.get("id") == task_id or t.get("task_id") == task_id:
            return t
    raise HTTPException(404, f"Task {task_id} not found")


@app.post("/api/tasks")
async def create_task(body: dict):
    """提交新任务（触发执行）"""
    task_id = body.get("id") or f"task_{int(time.time())}"
    task = {
        "id": task_id,
        "status": "pending",
        "prompt": body.get("prompt", ""),
        "created_at": datetime.now().isoformat(),
        "mode": body.get("mode", "spawn"),
    }
    _task_history.setdefault("tasks", []).append(task)
    _event_log.setdefault("events", []).append({
        "type": "task_created",
        "task_id": task_id,
        "timestamp": datetime.now().isoformat(),
    })
    await manager.broadcast({
        "type": "task_created",
        "task_id": task_id,
        "task": task,
        "timestamp": datetime.now().isoformat(),
    })

    # 触发异步执行
    asyncio.create_task(_execute_task_bg(task))

    return {"task_id": task_id, "status": "pending"}


async def _execute_task_bg(task: dict):
    """后台执行任务（写入结果文件供 AI 读取）"""
    from pathlib import Path
    results_dir = BASE_DIR / "swarm_data" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    task_id = task["id"]
    result_file = results_dir / f"spawn_{task_id}_{int(time.time())}.json"

    # 更新状态
    for t in _task_history["tasks"]:
        if t.get("id") == task_id:
            t["status"] = "running"
            t["started_at"] = datetime.now().isoformat()
            break

    await manager.broadcast({
        "type": "task_started",
        "task_id": task_id,
        "timestamp": datetime.now().isoformat(),
    })

    # 写入结果文件
    result = {
        "task_id": task_id,
        "status": "success",
        "output": f"[Dashboard Demo] 任务 {task_id} 已通过 Dashboard 提交。\n结果文件: {result_file}",
        "result_file": str(result_file),
        "completed_at": datetime.now().isoformat(),
    }

    try:
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    # 更新状态
    for t in _task_history["tasks"]:
        if t.get("id") == task_id:
            t["status"] = result["status"]
            t["completed_at"] = result["completed_at"]
            t["result_file"] = str(result_file)
            break

    await manager.broadcast({
        "type": "task_completed",
        "task_id": task_id,
        "result": result,
        "timestamp": datetime.now().isoformat(),
    })


@app.get("/api/events")
async def get_events(limit: int = Query(100, ge=1, le=500)):
    """获取事件日志"""
    events = _event_log.get("events", [])
    return {"total": len(events), "events": events[-limit:]}


# ── 节点管理 API ─────────────────────────────────────────────────────

@app.get("/api/relay/status")
async def get_relay_status():
    """获取 Relay 服务状态"""
    client = get_relay_client()
    if not client:
        return {"error": "Relay 客户端未初始化", "relay_url": RELAY_URL}
    try:
        status = client.get_status()
        return {"relay_url": RELAY_URL, "relay_reachable": client.ping(), "status": status}
    except Exception as e:
        return {"error": str(e), "relay_url": RELAY_URL}


@app.get("/api/relay/nodes")
async def get_relay_nodes():
    """获取通过 Relay 注册的远程节点"""
    client = get_relay_client()
    if not client:
        return {"nodes": [], "error": "Relay 客户端未初始化"}
    try:
        nodes = client.discover_nodes()
        return {"nodes": nodes, "total": len(nodes)}
    except Exception as e:
        return {"nodes": [], "error": str(e)}


@app.get("/api/nodes/{node_id}")
async def get_remote_node(node_id: str):
    """获取指定节点信息"""
    client = get_relay_client()
    if not client:
        raise HTTPException(503, "Relay 客户端未初始化")
    node = client.get_node(node_id)
    if not node:
        raise HTTPException(404, f"节点未找到: {node_id}")
    return node


@app.post("/api/cmd/{node_id}")
async def exec_on_node(node_id: str, body: dict = None):
    """在指定节点执行命令"""
    client = get_relay_client()
    if not client:
        raise HTTPException(503, "Relay 客户端未初始化")
    command = (body or {}).get("command", "")
    if not command:
        raise HTTPException(400, "command is required")
    timeout = (body or {}).get("timeout", 60)
    cwd = (body or {}).get("cwd", "/root")
    try:
        result = client.exec_on_node(node_id, command, timeout=timeout, cwd=cwd)
        return result
    except Exception as e:
        return {"status": "error", "output": str(e), "node_id": node_id}


@app.post("/api/pairing/generate")
async def generate_pair_code():
    """生成本机配对码（需要配置 relay）"""
    client = get_relay_client()
    if not client:
        raise HTTPException(503, "Relay 客户端未初始化，请设置 RELAY_URL 环境变量")
    try:
        # 使用 ClawPairing 生成配对码
        from pairing import ClawPairing
        pairing = ClawPairing(
            relay_url=RELAY_URL,
            node_id=RELAY_NODE_ID,
            gateway_url="http://localhost:28789",
            token=RELAY_TOKEN,
        )
        code = pairing.generate_code()
        return {"code": code, "relay_url": RELAY_URL}
    except Exception as e:
        raise HTTPException(500, f"配对码生成失败: {str(e)}")


@app.post("/api/pairing/connect")
async def connect_pair_code(body: dict):
    """使用配对码连接到对方节点"""
    code = (body or {}).get("code", "")
    if not code:
        raise HTTPException(400, "配对码不能为空")
    client = get_relay_client()
    if not client:
        raise HTTPException(503, "Relay 客户端未初始化")
    try:
        from pairing import ClawPairing
        pairing = ClawPairing(
            relay_url=RELAY_URL,
            node_id=RELAY_NODE_ID,
            gateway_url="http://localhost:28789",
            token=RELAY_TOKEN,
        )
        result = pairing.connect_with_code(code)
        return result
    except Exception as e:
        raise HTTPException(500, f"连接失败: {str(e)}")


@app.get("/api/pairing/status/{code}")
async def get_pair_status(code: str):
    """查询配对码状态"""
    client = get_relay_client()
    if not client:
        raise HTTPException(503, "Relay 客户端未初始化")
    try:
        from pairing import ClawPairing
        pairing = ClawPairing(
            relay_url=RELAY_URL,
            node_id=RELAY_NODE_ID,
            gateway_url="http://localhost:28789",
            token=RELAY_TOKEN,
        )
        status = pairing.get_connection_status(code)
        return status or {"status": "unknown"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Dashboard 任务执行 ──────────────────────────────────────────────

async def _execute_dashboard_task(task_id: str, description: str):
    """通过 orchestrator 执行 dashboard 提交的任务"""
    try:
        # 广播任务开始
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "running",
            "description": description[:100],
            "timestamp": datetime.now().isoformat(),
        })

        # 调用 orchestrator 执行
        try:
            from clawswarm.orchestrator import run
            result = run(description, timeout=60.0)
            await manager.broadcast({
                "type": "task_update",
                "task_id": task_id,
                "status": "done",
                "result": result[:500] if result else "(空)",
                "timestamp": datetime.now().isoformat(),
            })
        except ImportError:
            # clawswarm 不在 path，降级到 subprocess
            import subprocess
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c",
                f"import sys; sys.path.insert(0, r'{_CLAWSWARM_ROOT}'); "
                f"from orchestrator import run; print(run({repr(description)}, timeout=60))",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            result = stdout.decode("utf-8", errors="replace")
            await manager.broadcast({
                "type": "task_update",
                "task_id": task_id,
                "status": "done" if proc.returncode == 0 else "error",
                "result": result[:500] or stderr.decode()[:200],
                "timestamp": datetime.now().isoformat(),
            })
    except Exception as e:
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "error",
            "error": str(e)[:200],
            "timestamp": datetime.now().isoformat(),
        })


# ── WebSocket 端点 ──────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """实时 WebSocket 流"""
    await manager.connect(websocket)
    try:
        while True:
            # 接收客户端消息（保持连接活跃）
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                msg = json.loads(data)
                # 处理客户端命令
                if msg.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat(),
                    })
                elif msg.get("type") == "subscribe":
                    # 客户端订阅特定事件类型
                    await websocket.send_json({
                        "type": "subscribed",
                        "topics": msg.get("topics", []),
                        "timestamp": datetime.now().isoformat(),
                    })
                elif msg.get("type") == "submit":
                    # 客户端提交新任务
                    description = msg.get("description", "")
                    task_id = f"dash_{int(time.time()*1000)}"
                    if description:
                        # 异步执行（不阻塞 WebSocket 连接）
                        asyncio.create_task(_execute_dashboard_task(task_id, description))
                    await websocket.send_json({
                        "type": "task_submitted",
                        "task_id": task_id,
                        "description": description[:100],
                        "timestamp": datetime.now().isoformat(),
                    })
            except asyncio.TimeoutError:
                # 发送心跳保持连接
                await websocket.send_json({
                    "type": "heartbeat",
                    "timestamp": datetime.now().isoformat(),
                })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await manager.disconnect(websocket)


# ── HTML 主页 ────────────────────────────────────────────────────────

def _load_dashboard_html() -> str:
    """从 index.html 文件读取 Dashboard 页面（避免内嵌巨型字符串）"""
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>Dashboard HTML not found</h1>"

DASHBOARD_HTML = _load_dashboard_html()

# 旧版内嵌 HTML 已迁移到 dashboard/index.html，不再在 Python 中维护




@app.get("/", response_class=HTMLResponse)
async def root():
    return DASHBOARD_HTML

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_alias():
    return DASHBOARD_HTML


# ── Lifespan（替代废弃的 on_event）─────────────────────────────────────




# ── CLI 入口 ─────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ClawSwarm Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=5000, help="监听端口")
    args = parser.parse_args()

    print("ClawSwarm Dashboard starting...")
    print(f"   Address: http://{args.host}:{args.port}")
    print(f"   WebSocket: ws://{args.host}:{args.port}/ws")

    # 在主线程启动后台收集协程
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(_collect_events())
    loop.run_in_executor(None, loop.run_forever)

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
