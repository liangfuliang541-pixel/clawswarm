"""
ClawSwarm API - REST API 服务器
负责：HTTP API、任务提交、状态查询、Webhook

支持：
- FastAPI
- 任务 CRUD
- 节点状态
- 指标查询
- Webhook 回调
"""

import json
import os
import asyncio
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

# ── 尝试导入 FastAPI ─────────────────────────────────────────────────

try:
    from fastapi import FastAPI, HTTPException, Request, Response
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    # 提供一个简单的占位实现
    FastAPI = None

# ── 数据模型 ─────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskPriority(int, Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3

@dataclass
class Task:
    """任务"""
    id: str
    type: str
    description: str
    prompt: str = ""
    mode: str = "spawn"
    priority: int = TaskPriority.NORMAL
    status: str = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    node_id: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Node:
    """节点"""
    id: str
    name: str
    status: str  # online, stale, offline
    capabilities: List[str] = field(default_factory=list)
    registered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_heartbeat: str = field(default_factory=lambda: datetime.now().isoformat())
    tasks_completed: int = 0
    tasks_failed: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class APIResponse:
    """API 响应"""
    success: bool
    data: Any = None
    error: str = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

# ── API 服务器 ─────────────────────────────────────────────────────────

class APIServer:
    """
    API 服务器
    
    用法:
        server = APIServer(swarm_dir="D:\\claw\\swarm")
        server.start()
    """
    
    def __init__(
        self,
        swarm_dir: str,
        host: str = "0.0.0.0",
        port: int = 8080,
        cors: bool = True
    ):
        self.swarm_dir = swarm_dir
        self.host = host
        self.port = port
        self.cors_enabled = cors
        
        self._app = None
        self._server = None
        self._running = False
        
        # 任务队列
        self._tasks: Dict[str, Task] = {}
        self._nodes: Dict[str, Node] = {}
        
        # 回调
        self._on_task_created: List[callable] = []
        self._on_task_completed: List[callable] = []
    
    @property
    def app(self):
        """获取 FastAPI 应用"""
        if not FASTAPI_AVAILABLE:
            raise RuntimeError("FastAPI not installed. Run: pip install fastapi uvicorn")
        
        if self._app is None:
            self._app = self._create_app()
        
        return self._app
    
    def _create_app(self) -> FastAPI:
        """创建 FastAPI 应用"""
        app = FastAPI(
            title="ClawSwarm API",
            description="Multi-Agent Orchestration System",
            version="0.1.0"
        )
        
        # CORS
        if self.cors_enabled:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        
        # 注册路由
        self._register_routes(app)
        
        return app
    
    def _register_routes(self, app: FastAPI):
        """注册路由"""
        
        # ── 根路径 ─────────────────────────────────────────────────────
        
        @app.get("/")
        async def root():
            return APIResponse(
                success=True,
                data={
                    "name": "ClawSwarm",
                    "version": "0.1.0",
                    "status": "running"
                }
            )
        
        @app.get("/health")
        async def health():
            return {"status": "healthy", "timestamp": datetime.now().isoformat()}
        
        # ── 任务 ─────────────────────────────────────────────────────
        
        @app.post("/api/tasks")
        async def create_task(request: Request):
            """创建任务"""
            body = await request.json()
            
            # 生成任务 ID
            task_id = body.get("id") or f"task_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            
            task = Task(
                id=task_id,
                type=body.get("type", "general"),
                description=body.get("description", ""),
                prompt=body.get("prompt", body.get("description", "")),
                mode=body.get("mode", "spawn"),
                priority=body.get("priority", TaskPriority.NORMAL),
                metadata=body.get("metadata", {})
            )
            
            self._tasks[task_id] = task
            
            # 保存到文件
            self._save_task(task)
            
            # 触发回调
            for callback in self._on_task_created:
                try:
                    callback(task)
                except Exception:
                    pass
            
            return APIResponse(
                success=True,
                data=task.__dict__
            )
        
        @app.get("/api/tasks")
        async def list_tasks(
            status: str = None,
            limit: int = 100,
            offset: int = 0
        ):
            """列出任务"""
            tasks = list(self._tasks.values())
            
            if status:
                tasks = [t for t in tasks if t.status == status]
            
            tasks = tasks[offset:offset + limit]
            
            return APIResponse(
                success=True,
                data=[t.__dict__ for t in tasks]
            )
        
        @app.get("/api/tasks/{task_id}")
        async def get_task(task_id: str):
            """获取任务详情"""
            if task_id not in self._tasks:
                raise HTTPException(status_code=404, detail="Task not found")
            
            return APIResponse(
                success=True,
                data=self._tasks[task_id].__dict__
            )
        
        @app.delete("/api/tasks/{task_id}")
        async def cancel_task(task_id: str):
            """取消任务"""
            if task_id not in self._tasks:
                raise HTTPException(status_code=404, detail="Task not found")
            
            task = self._tasks[task_id]
            
            if task.status in [TaskStatus.DONE, TaskStatus.FAILED]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot cancel task with status: {task.status}"
                )
            
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now().isoformat()
            
            # 保存
            self._save_task(task)
            
            return APIResponse(
                success=True,
                data=task.__dict__
            )
        
        # ── 节点 ─────────────────────────────────────────────────────
        
        @app.post("/api/nodes")
        async def register_node(request: Request):
            """注册节点"""
            body = await request.json()
            
            node_id = body.get("id")
            if not node_id:
                raise HTTPException(status_code=400, detail="Node ID required")
            
            node = Node(
                id=node_id,
                name=body.get("name", node_id),
                capabilities=body.get("capabilities", []),
                metadata=body.get("metadata", {})
            )
            
            self._nodes[node_id] = node
            
            return APIResponse(
                success=True,
                data=node.__dict__
            )
        
        @app.get("/api/nodes")
        async def list_nodes(status: str = None):
            """列出节点"""
            nodes = list(self._nodes.values())
            
            if status:
                nodes = [n for n in nodes if n.status == status]
            
            return APIResponse(
                success=True,
                data=[n.__dict__ for n in nodes]
            )
        
        @app.get("/api/nodes/{node_id}")
        async def get_node(node_id: str):
            """获取节点详情"""
            if node_id not in self._nodes:
                raise HTTPException(status_code=404, detail="Node not found")
            
            return APIResponse(
                success=True,
                data=self._nodes[node_id].__dict__
            )
        
        @app.post("/api/nodes/{node_id}/heartbeat")
        async def node_heartbeat(node_id: str, request: Request):
            """节点心跳"""
            if node_id not in self._nodes:
                raise HTTPException(status_code=404, detail="Node not found")
            
            body = await request.json()
            
            node = self._nodes[node_id]
            node.status = "online"
            node.last_heartbeat = datetime.now().isoformat()
            
            if "tasks_completed" in body:
                node.tasks_completed = body["tasks_completed"]
            if "tasks_failed" in body:
                node.tasks_failed = body["tasks_failed"]
            if "metadata" in body:
                node.metadata.update(body["metadata"])
            
            return APIResponse(success=True)
        
        # ── 统计 ─────────────────────────────────────────────────────
        
        @app.get("/api/stats")
        async def get_stats():
            """获取统计信息"""
            tasks = list(self._tasks.values())
            nodes = list(self._nodes.values())
            
            return APIResponse(
                success=True,
                data={
                    "tasks": {
                        "total": len(tasks),
                        "pending": len([t for t in tasks if t.status == TaskStatus.PENDING]),
                        "running": len([t for t in tasks if t.status == TaskStatus.RUNNING]),
                        "done": len([t for t in tasks if t.status == TaskStatus.DONE]),
                        "failed": len([t for t in tasks if t.status == TaskStatus.FAILED]),
                    },
                    "nodes": {
                        "total": len(nodes),
                        "online": len([n for n in nodes if n.status == "online"]),
                        "stale": len([n for n in nodes if n.status == "stale"]),
                        "offline": len([n for n in nodes if n.status == "offline"]),
                    },
                    "timestamp": datetime.now().isoformat()
                }
            )
        
        # ── Webhook ─────────────────────────────────────────────────────
        
        @app.post("/api/webhook/task")
        async def webhook_task(request: Request):
            """Webhook - 任务事件"""
            body = await request.json()
            
            event = body.get("event")
            task_id = body.get("task_id")
            
            if event == "task.completed":
                if task_id in self._tasks:
                    task = self._tasks[task_id]
                    task.status = TaskStatus.DONE
                    task.result = body.get("result")
                    task.completed_at = datetime.now().isoformat()
                    self._save_task(task)
            
            elif event == "task.failed":
                if task_id in self._tasks:
                    task = self._tasks[task_id]
                    task.status = TaskStatus.FAILED
                    task.error = body.get("error")
                    task.completed_at = datetime.now().isoformat()
                    self._save_task(task)
            
            return APIResponse(success=True)
    
    # ── 文件操作 ─────────────────────────────────────────────────────────
    
    def _save_task(self, task: Task):
        """保存任务到文件"""
        try:
            # 这里可以调用 swarm 的任务保存逻辑
            pass
        except Exception:
            pass
    
    # ── 生命周期 ─────────────────────────────────────────────────────────
    
    def start(self, blocking: bool = True):
        """启动服务器"""
        if not FASTAPI_AVAILABLE:
            raise RuntimeError("FastAPI not available")
        
        if self._running:
            return
        
        # 使用 uvicorn 运行
        try:
            import uvicorn
        except ImportError:
            raise RuntimeError("uvicorn not installed. Run: pip install uvicorn")
        
        self._running = True
        
        if blocking:
            uvicorn.run(
                self.app,
                host=self.host,
                port=self.port,
                log_level="info"
            )
        else:
            # 后台运行
            def run():
                uvicorn.run(
                    self.app,
                    host=self.host,
                    port=self.port,
                    log_level="warning"
                )
            
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
    
    def stop(self):
        """停止服务器"""
        self._running = False
    
    # ── 回调 ─────────────────────────────────────────────────────────
    
    def on_task_created(self, callback: callable):
        """任务创建回调"""
        self._on_task_created.append(callback)
    
    def on_task_completed(self, callback: callable):
        """任务完成回调"""
        self._on_task_completed.append(callback)


# ── 便捷函数 ─────────────────────────────────────────────────────────

def create_server(
    swarm_dir: str,
    host: str = "0.0.0.0",
    port: int = 8080
) -> APIServer:
    """创建 API 服务器"""
    return APIServer(swarm_dir=swarm_dir, host=host, port=port)


# ── 测试 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not FASTAPI_AVAILABLE:
        print("FastAPI not installed. Installing...")
        os.system("pip install fastapi uvicorn")
    
    print("=" * 50)
    print("ClawSwarm API Server")
    print("=" * 50)
    print("\n启动服务器...")
    print("访问 http://localhost:8080/docs 查看 API 文档")
    
    server = create_server(swarm_dir=".", port=8080)
    server.start()
