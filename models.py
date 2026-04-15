"""
ClawSwarm 数据模型

定义系统中使用的所有数据模型
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import json

# ── 枚举 ───────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(int, Enum):
    """任务优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


class TaskMode(str, Enum):
    """任务执行模式"""
    SPAWN = "spawn"       # 启动子 Agent
    FETCH = "fetch"       # 网页抓取
    EXEC = "exec"         # 系统命令
    PYTHON = "python"     # Python 代码
    WORKFLOW = "workflow" # 工作流


class NodeStatus(str, Enum):
    """节点状态"""
    ONLINE = "online"
    STALE = "stale"
    OFFLINE = "offline"


class ExecutionMode(str, Enum):
    """执行模式"""
    SYNC = "sync"
    ASYNC = "async"
    PARALLEL = "parallel"


# ── 任务模型 ─────────────────────────────────────────────────────────

@dataclass
class Task:
    """任务"""
    id: str
    type: str = "general"
    description: str = ""
    prompt: str = ""
    mode: TaskMode = TaskMode.SPAWN
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    
    # 时间戳
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    # 执行信息
    node_id: Optional[str] = None
    worker_id: Optional[str] = None
    
    # 结果
    result: Any = None
    error: Optional[str] = None
    output: Optional[str] = None
    
    # 重试
    retry_count: int = 0
    max_retries: int = 3
    
    # 超时
    timeout_seconds: int = 300
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    
    # 依赖
    depends_on: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "prompt": self.prompt,
            "mode": self.mode.value if isinstance(self.mode, Enum) else self.mode,
            "priority": self.priority.value if isinstance(self.priority, Enum) else self.priority,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "node_id": self.node_id,
            "worker_id": self.worker_id,
            "result": self.result,
            "error": self.error,
            "output": self.output,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
            "tags": self.tags,
            "depends_on": self.depends_on,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        """从字典创建"""
        # 处理枚举
        if "mode" in data and isinstance(data["mode"], str):
            data["mode"] = TaskMode(data["mode"])
        if "priority" in data and isinstance(data["priority"], int):
            data["priority"] = TaskPriority(data["priority"])
        if "status" in data and isinstance(data["status"], str):
            data["status"] = TaskStatus(data["status"])
        
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})
    
    def to_json(self) -> str:
        """转换为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)
    
    @classmethod
    def from_json(cls, json_str: str) -> "Task":
        """从 JSON 创建"""
        return cls.from_dict(json.loads(json_str))


# ── 节点模型 ─────────────────────────────────────────────────────────

@dataclass
class Node:
    """节点"""
    id: str
    name: str = ""
    status: NodeStatus = NodeStatus.OFFLINE
    
    # 能力
    capabilities: List[str] = field(default_factory=list)
    max_concurrent_tasks: int = 1
    
    # 时间
    registered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_heartbeat: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    
    # 统计
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_running: int = 0
    
    # 资源
    cpu_percent: float = 0
    memory_percent: float = 0
    disk_percent: float = 0
    
    # 配置
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 端点
    endpoint: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "capabilities": self.capabilities,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
            "started_at": self.started_at,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "tasks_running": self.tasks_running,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
            "config": self.config,
            "metadata": self.metadata,
            "endpoint": self.endpoint,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Node":
        """从字典创建"""
        if "status" in data and isinstance(data["status"], str):
            data["status"] = NodeStatus(data["status"])
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


# ── 工作流模型 ─────────────────────────────────────────────────────

@dataclass
class WorkflowStep:
    """工作流步骤"""
    id: str
    name: str = ""
    mode: TaskMode = TaskMode.SPAWN
    
    # 输入
    input: Any = None
    
    # 配置
    config: Dict[str, Any] = field(default_factory=dict)
    
    # 条件
    condition: Optional[str] = None
    continue_on_error: bool = False
    
    # 重试
    retry_count: int = 0
    retry_delay: float = 1.0
    
    # 依赖
    depends_on: List[str] = field(default_factory=list)


@dataclass
class Workflow:
    """工作流"""
    id: str
    name: str = ""
    description: str = ""
    
    # 步骤
    steps: List[WorkflowStep] = field(default_factory=list)
    
    # 配置
    parallel: bool = False
    max_parallel: int = 5
    
    # 状态
    status: TaskStatus = TaskStatus.PENDING
    current_step: Optional[str] = None
    
    # 时间
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    # 结果
    results: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


# ── 执行结果模型 ─────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    """执行结果"""
    task_id: str
    status: TaskStatus
    
    # 输出
    output: Any = None
    error: Optional[str] = None
    
    # 时间
    duration_seconds: float = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    
    # 重试
    retries: int = 0
    
    # 节点
    node_id: Optional[str] = None
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "output": self.output,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "retries": self.retries,
            "node_id": self.node_id,
            "metadata": self.metadata,
        }


# ── 统计模型 ─────────────────────────────────────────────────────────

@dataclass
class ClusterStats:
    """集群统计"""
    # 任务
    tasks_pending: int = 0
    tasks_running: int = 0
    tasks_done: int = 0
    tasks_failed: int = 0
    tasks_cancelled: int = 0
    
    # 节点
    nodes_online: int = 0
    nodes_stale: int = 0
    nodes_offline: int = 0
    
    # 资源
    total_cpu_percent: float = 0
    total_memory_percent: float = 0
    
    # 时间
    uptime_seconds: float = 0
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "tasks": {
                "pending": self.tasks_pending,
                "running": self.tasks_running,
                "done": self.tasks_done,
                "failed": self.tasks_failed,
                "cancelled": self.tasks_cancelled,
            },
            "nodes": {
                "online": self.nodes_online,
                "stale": self.nodes_stale,
                "offline": self.nodes_offline,
            },
            "resources": {
                "cpu_percent": self.total_cpu_percent,
                "memory_percent": self.total_memory_percent,
            },
            "uptime_seconds": self.uptime_seconds,
            "last_updated": self.last_updated,
        }


# ── 便捷函数 ─────────────────────────────────────────────────────────

def create_task(
    description: str,
    prompt: str = None,
    task_type: str = "general",
    mode: str = "spawn",
    priority: int = 1,
    **kwargs
) -> Task:
    """创建任务"""
    task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    
    return Task(
        id=task_id,
        type=task_type,
        description=description,
        prompt=prompt or description,
        mode=TaskMode(mode),
        priority=TaskPriority(priority),
        **kwargs
    )


def create_node(
    node_id: str,
    name: str = None,
    capabilities: List[str] = None,
    **kwargs
) -> Node:
    """创建节点"""
    return Node(
        id=node_id,
        name=name or node_id,
        capabilities=capabilities or ["general"],
        **kwargs
    )


# ── 序列化 ─────────────────────────────────────────────────────────

class JSONEncoder(json.JSONEncoder):
    """自定义 JSON 编码器"""
    
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return super().default(obj)


def to_json(obj, indent: int = 2) -> str:
    """转换为 JSON"""
    return json.dumps(obj, cls=JSONEncoder, ensure_ascii=False, indent=indent)


# ── 测试 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("数据模型测试")
    print("=" * 50)
    
    # 创建任务
    task = create_task(
        description="测试任务",
        prompt="执行一个测试",
        priority=2
    )
    
    print(f"\n任务: {task.id}")
    print(f"状态: {task.status.value}")
    print(f"优先级: {task.priority.value}")
    
    # 序列化
    json_str = task.to_json()
    print(f"\nJSON: {json_str[:100]}...")
    
    # 反序列化
    task2 = Task.from_json(json_str)
    print(f"\n反序列化: {task2.id}")
    
    # 创建节点
    node = create_node(
        node_id="node-001",
        name="测试节点",
        capabilities=["web", "compute"]
    )
    
    print(f"\n节点: {node.id}")
    print(f"能力: {node.capabilities}")
    
    # 统计
    stats = ClusterStats(
        tasks_pending=5,
        tasks_running=2,
        tasks_done=10,
        nodes_online=3
    )
    
    print(f"\n统计: {to_json(stats)}")
    
    print("\n测试完成!")
