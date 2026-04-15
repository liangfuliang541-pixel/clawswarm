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
    """获取节点列表"""
    if HAS_CLAWSWARM:
        try:
            monitor = get_monitor()
            status = monitor.get_status()
            return status.get("nodes", {"total": 0, "online": 0, "list": []})
        except Exception as e:
            return {"total": 0, "online": 0, "list": [], "error": str(e)}
    return {"total": 0, "online": 0, "list": []}


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

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🦞 ClawSwarm — 龙虾控制台</title>
<style>
  :root {
    --bg: #0a0e17;
    --surface: #111827;
    --border: #1f2937;
    --text: #e5e7eb;
    --muted: #9ca3af;
    --accent: #3b82f6;
    --green: #10b981;
    --yellow: #f59e0b;
    --red: #ef4444;
    --purple: #8b5cf6;
    --pink: #ec4899;
    --cyan: #06b6d4;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    min-height: 100vh;
  }
  /* Header */
  .header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .header .logo { font-size: 20px; }
  .header .subtitle { color: var(--muted); font-size: 13px; }
  .status-badge {
    margin-left: auto;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    border: 1px solid;
  }
  .status-badge.online { background: rgba(16,185,129,0.1); border-color: var(--green); color: var(--green); }
  .status-badge.offline { background: rgba(239,68,68,0.1); border-color: var(--red); color: var(--red); }
  .status-badge.demo { background: rgba(139,92,246,0.1); border-color: var(--purple); color: var(--purple); }

  /* Layout */
  .layout { display: grid; grid-template-columns: 260px 1fr 300px; gap: 0; height: calc(100vh - 53px); overflow: hidden; }

  /* Sidebar */
  .sidebar {
    background: var(--surface);
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 16px;
  }
  .sidebar h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 12px; }
  .node-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 8px;
    transition: border-color 0.2s;
  }
  .node-card:hover { border-color: var(--accent); }
  .node-card .name { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
  .node-card .meta { font-size: 11px; color: var(--muted); }
  .node-card .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .dot.online { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .dot.offline { background: var(--red); }

  /* Main */
  .main { overflow-y: auto; padding: 16px; }

  /* Stats row */
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
    text-align: center;
  }
  .stat-card .value { font-size: 28px; font-weight: 700; }
  .stat-card .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }
  .stat-card.blue .value { color: var(--accent); }
  .stat-card.green .value { color: var(--green); }
  .stat-card.yellow .value { color: var(--yellow); }
  .stat-card.purple .value { color: var(--purple); }

  /* DAG Canvas */
  .dag-section { margin-bottom: 20px; }
  .section-title { font-size: 13px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
  .dag-container {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    min-height: 180px;
    overflow-x: auto;
  }
  .dag-canvas { position: relative; min-width: 100%; min-height: 140px; }
  .dag-node {
    position: absolute;
    background: var(--bg);
    border: 2px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    min-width: 120px;
    text-align: center;
  }
  .dag-node:hover { border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
  .dag-node.pending { border-color: var(--yellow); color: var(--yellow); }
  .dag-node.running { border-color: var(--accent); color: var(--accent); box-shadow: 0 0 12px rgba(59,130,246,0.3); }
  .dag-node.success { border-color: var(--green); color: var(--green); }
  .dag-node.failed { border-color: var(--red); color: var(--red); }
  .dag-node .task-id { font-size: 10px; color: var(--muted); margin-top: 4px; font-weight: 400; }
  .dag-node .spinner {
    display: inline-block; width: 12px; height: 12px;
    border: 2px solid var(--accent);
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-right: 4px;
    vertical-align: middle;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .dag-line {
    position: absolute;
    height: 2px;
    background: var(--border);
    transform-origin: 0 50%;
    pointer-events: none;
  }
  .dag-arrow {
    position: absolute;
    width: 0; height: 0;
    border-left: 6px solid var(--border);
    border-top: 3px solid transparent;
    border-bottom: 3px solid transparent;
    pointer-events: none;
  }

  /* Task Panel */
  .right-panel {
    background: var(--surface);
    border-left: 1px solid var(--border);
    overflow-y: auto;
    padding: 16px;
  }
  .right-panel h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 12px; }

  .task-item {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    margin-bottom: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: border-color 0.2s;
  }
  .task-item:hover { border-color: var(--accent); }
  .task-item .top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .task-item .task-id { color: var(--muted); font-size: 10px; }
  .task-item .status-tag {
    font-size: 10px; padding: 2px 6px; border-radius: 4px;
    font-weight: 600; text-transform: uppercase;
  }
  .status-tag.pending { background: rgba(245,158,11,0.15); color: var(--yellow); }
  .status-tag.running { background: rgba(59,130,246,0.15); color: var(--accent); }
  .status-tag.success { background: rgba(16,185,129,0.15); color: var(--green); }
  .status-tag.failed { background: rgba(239,68,68,0.15); color: var(--red); }
  .task-item .prompt { color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* Event Log */
  .event-log { margin-top: 16px; }
  .event-item {
    font-size: 11px;
    padding: 4px 0;
    border-bottom: 1px solid var(--border);
    color: var(--muted);
  }
  .event-item .time { color: var(--cyan); margin-right: 6px; }
  .event-item.task_created .msg { color: var(--yellow); }
  .event-item.task_completed .msg { color: var(--green); }
  .event-item.task_started .msg { color: var(--accent); }
  .event-item.node_status_change .msg { color: var(--purple); }

  /* New Task Form */
  .new-task {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
    margin-bottom: 16px;
  }
  .new-task textarea {
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: inherit;
    font-size: 12px;
    padding: 10px;
    resize: vertical;
    min-height: 80px;
    margin-bottom: 8px;
  }
  .new-task textarea:focus { outline: none; border-color: var(--accent); }
  .new-task button {
    width: 100%;
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px;
    font-family: inherit;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s;
  }
  .new-task button:hover { opacity: 0.85; }
  .new-task button:active { opacity: 0.7; }

  /* Connection indicator */
  .conn-indicator {
    position: fixed;
    bottom: 16px;
    right: 16px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--red);
    transition: background 0.3s;
    box-shadow: 0 0 8px var(--red);
  }
  .conn-indicator.connected { background: var(--green); box-shadow: 0 0 8px var(--green); }

  /* Empty state */
  .empty-state {
    text-align: center;
    color: var(--muted);
    font-size: 13px;
    padding: 40px 20px;
  }
  .empty-state .emoji { font-size: 36px; margin-bottom: 12px; }
</style>
</head>
<body>

<div class="header">
  <span class="logo">🦞</span>
  <span class="subtitle">ClawSwarm Dashboard</span>
  <span class="status-badge demo" id="statusBadge">DEMO</span>
</div>

<div class="layout">
  <!-- Left: Nodes -->
  <div class="sidebar">
    <h3>🐠 龙虾节点</h3>
    <div id="nodeList">
      <div class="empty-state"><div class="emoji">🦞</div>等待连接...</div>
    </div>
  </div>

  <!-- Center: Main -->
  <div class="main">
    <!-- Stats -->
    <div class="stats">
      <div class="stat-card blue">
        <div class="value" id="statNodes">0</div>
        <div class="label">节点</div>
      </div>
      <div class="stat-card green">
        <div class="value" id="statOnline">0</div>
        <div class="label">在线</div>
      </div>
      <div class="stat-card yellow">
        <div class="value" id="statPending">0</div>
        <div class="label">待执行</div>
      </div>
      <div class="stat-card purple">
        <div class="value" id="statDone">0</div>
        <div class="label">已完成</div>
      </div>
    </div>

    <!-- New Task -->
    <div class="new-task">
      <h3 class="section-title">➕ 提交新任务</h3>
      <textarea id="taskPrompt" placeholder="用自然语言描述任务... 例如：搜索 AI Agent 最新进展，分析趋势，写一份报告"></textarea>
      <button onclick="submitTask()">🚀 启动任务</button>
    </div>

    <!-- DAG -->
    <div class="dag-section">
      <h3 class="section-title">🔀 任务 DAG</h3>
      <div class="dag-container">
        <div class="dag-canvas" id="dagCanvas"></div>
      </div>
    </div>
  </div>

  <!-- Right: Tasks + Events -->
  <div class="right-panel">
    <h3>📋 任务列表</h3>
    <div id="taskList">
      <div class="empty-state">暂无任务</div>
    </div>

    <div class="event-log">
      <h3>📡 实时事件</h3>
      <div id="eventLog"></div>
    </div>
  </div>
</div>

<div class="conn-indicator" id="connIndicator" title="WebSocket 连接状态"></div>

<script>
const WS_URL = `ws://${location.host}/ws`;
let ws = null;
let tasks = [];
let nodes = [];
let events = [];
let reconnectTimer = null;

// ── WebSocket ──────────────────────────────────────────────────────
function connect() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    document.getElementById('connIndicator').classList.add('connected');
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  };
  ws.onclose = ws.onerror = () => {
    document.getElementById('connIndicator').classList.remove('connected');
    reconnectTimer = setTimeout(connect, 3000);
  };
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      handleMessage(msg);
    } catch(err) { console.warn('bad msg', err); }
  };
}

function handleMessage(msg) {
  if (msg.type === 'init') {
    const d = msg.data;
    if (d.nodes) renderNodes(d.nodes.list || []);
    if (d.tasks) { tasks = d.tasks; renderTasks(); renderDAG(); }
    if (d.events) { events = d.events; renderEvents(); }
    if (d.swarm) updateSwarmStatus(d.swarm);
    updateStats();
  } else if (msg.type === 'task_created') {
    tasks.push(msg.task);
    renderTasks();
    renderDAG();
    updateStats();
    addEvent('task_created', `任务 ${msg.task_id} 已提交`);
  } else if (msg.type === 'task_started') {
    const t = tasks.find(t => t.id === msg.task_id);
    if (t) { t.status = 'running'; renderTasks(); renderDAG(); }
    updateStats();
    addEvent('task_started', `任务 ${msg.task_id} 开始执行`);
  } else if (msg.type === 'task_completed') {
    const t = tasks.find(t => t.id === msg.task_id);
    if (t) { Object.assign(t, msg.result); renderTasks(); renderDAG(); }
    updateStats();
    addEvent('task_completed', `任务 ${msg.task_id} 完成: ${msg.result.status}`);
  } else if (msg.type === 'node_status_change') {
    addEvent('node_status_change', `节点 ${msg.node_id}: ${msg.old} → ${msg.new}`);
  } else if (msg.type === 'heartbeat' || msg.type === 'ping' || msg.type === 'pong') {
    // ignore
  } else if (msg.data && msg.data.monitor) {
    renderNodes(msg.data.monitor.nodes?.list || []);
    updateStats();
  }
}

// ── Render ──────────────────────────────────────────────────────────
function renderNodes(nodeList) {
  nodes = nodeList;
  const el = document.getElementById('nodeList');
  if (!nodes.length) {
    el.innerHTML = '<div class="empty-state"><div class="emoji">🦞</div>Demo 模式 — 无节点</div>';
    return;
  }
  el.innerHTML = nodes.map(n => `
    <div class="node-card">
      <div class="name"><span class="dot ${n.status === 'online' ? 'online' : 'offline'}"></span>${n.node_id}</div>
      <div class="meta">${n.cpu ? 'CPU: ' + n.cpu.toFixed(1) + '%' : '状态: ' + (n.status || 'unknown')}</div>
      <div class="meta">${n.memory ? 'MEM: ' + n.memory.toFixed(1) + '%' : ''}</div>
      <div class="meta">已完成: ${n.tasks_completed || 0} 任务</div>
    </div>
  `).join('');
}

function renderTasks() {
  const el = document.getElementById('taskList');
  if (!tasks.length) { el.innerHTML = '<div class="empty-state">暂无任务</div>'; return; }
  el.innerHTML = tasks.slice().reverse().map(t => `
    <div class="task-item" onclick="focusTask('${t.id}')">
      <div class="top">
        <span class="task-id">#${t.id}</span>
        <span class="status-tag ${t.status || 'pending'}">${t.status || 'pending'}</span>
      </div>
      <div class="prompt">${t.prompt || t.description || ''}</div>
    </div>
  `).join('');
}

function renderDAG() {
  const canvas = document.getElementById('dagCanvas');
  if (!tasks.length) { canvas.innerHTML = '<div class="empty-state">提交任务后，任务 DAG 将在这里显示</div>'; return; }
  canvas.innerHTML = '';

  const W = 150, H = 60, GAP_X = 80, GAP_Y = 90;
  const cols = Math.ceil(Math.sqrt(tasks.length));
  const startX = 20, startY = 20;

  tasks.forEach((task, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const x = startX + col * (W + GAP_X);
    const y = startY + row * (H + GAP_Y);

    const el = document.createElement('div');
    el.className = `dag-node ${task.status || 'pending'}`;
    el.id = `dag-node-${task.id}`;
    el.style.left = x + 'px';
    el.style.top = y + 'px';
    el.innerHTML = `
      ${task.status === 'running' ? '<span class="spinner"></span>' : ''}
      ${task.status || 'pending'}
      <div class="task-id">#${task.id}</div>
    `;
    canvas.appendChild(el);
  });
}

function renderEvents() {
  const el = document.getElementById('eventLog');
  if (!events.length) return;
  el.innerHTML = events.slice(-20).reverse().map(e => `
    <div class="event-item ${e.type}">
      <span class="time">${new Date(e.timestamp).toLocaleTimeString()}</span>
      <span class="msg">${e.msg || e.type}</span>
    </div>
  `).join('');
}

function addEvent(type, msg) {
  events.push({ type, msg, timestamp: new Date().toISOString() });
  if (events.length > 100) events.shift();
  renderEvents();
}

function updateStats() {
  document.getElementById('statNodes').textContent = nodes.length;
  document.getElementById('statOnline').textContent = nodes.filter(n => n.status === 'online').length;
  document.getElementById('statPending').textContent = tasks.filter(t => t.status === 'pending' || t.status === 'running').length;
  document.getElementById('statDone').textContent = tasks.filter(t => t.status === 'success' || t.status === 'done').length;
}

function updateSwarmStatus(swarm) {
  const badge = document.getElementById('statusBadge');
  if (swarm.mode === 'demo') {
    badge.textContent = 'DEMO';
    badge.className = 'status-badge demo';
  } else if (swarm.initialized) {
    badge.textContent = 'LIVE';
    badge.className = 'status-badge online';
  } else {
    badge.textContent = 'OFFLINE';
    badge.className = 'status-badge offline';
  }
}

function focusTask(taskId) {
  const el = document.getElementById(`dag-node-${taskId}`);
  if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.style.boxShadow = '0 0 20px var(--accent)'; setTimeout(() => el.style.boxShadow = '', 1500); }
}

// ── Submit Task ────────────────────────────────────────────────────
async function submitTask() {
  const prompt = document.getElementById('taskPrompt').value.trim();
  if (!prompt) return;
  document.getElementById('taskPrompt').value = '';
  try {
    const res = await fetch('/api/tasks', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ prompt }),
    });
    const data = await res.json();
    addEvent('info', `已提交: ${data.task_id}`);
  } catch(e) {
    addEvent('error', '提交失败: ' + e.message);
  }
}

// ── Init ─────────────────────────────────────────────────────────────
connect();
</script>
</body>
</html>
"""


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
