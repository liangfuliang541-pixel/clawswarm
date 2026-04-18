"""
task_queue.py — 高级任务队列系统
支持优先级、重试、延迟执行、死信队列
"""

import asyncio
import json
import time
import heapq
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
import threading


class TaskPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class TaskStatus(Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"  # 延迟执行
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    DEAD = "dead"  # 死信队列


@dataclass(order=True)
class QueuedTask:
    """可排序的任务项"""
    priority: int
    created_at: float = field(compare=False)
    task_id: str = field(compare=False)
    payload: Dict[str, Any] = field(compare=False, default_factory=dict)
    status: TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    
    # 重试配置
    max_retries: int = field(compare=False, default=3)
    retry_count: int = field(compare=False, default=0)
    retry_delay: float = field(compare=False, default=5.0)  # 指数退避基数
    
    # 调度配置
    scheduled_at: Optional[float] = field(compare=False, default=None)
    deadline: Optional[float] = field(compare=False, default=None)
    
    # 执行信息
    assigned_to: Optional[str] = field(compare=False, default=None)
    started_at: Optional[float] = field(compare=False, default=None)
    completed_at: Optional[float] = field(compare=False, default=None)
    error: Optional[str] = field(compare=False, default=None)
    result: Any = field(compare=False, default=None)
    
    # 元数据
    tags: Set[str] = field(compare=False, default_factory=set)
    metadata: Dict[str, Any] = field(compare=False, default_factory=dict)


class TaskQueue:
    """线程安全的高级任务队列"""
    
    def __init__(self, storage_path: Optional[Path] = None, max_dead_letter: int = 1000):
        self._heap: List[QueuedTask] = []
        self._lock = threading.RLock()
        self._tasks: Dict[str, QueuedTask] = {}
        self._running: Dict[str, QueuedTask] = {}
        self._dead_letter: List[QueuedTask] = []
        self._max_dead_letter = max_dead_letter
        
        self._storage_path = storage_path
        self._shutdown = False
        self._worker_thread: Optional[threading.Thread] = None
        self._callbacks: Dict[str, List[Callable]] = {
            'on_submit': [],
            'on_start': [],
            'on_complete': [],
            'on_fail': [],
            'on_retry': [],
            'on_dead': [],
        }
        
        if storage_path:
            self._load_from_disk()
    
    def submit(
        self,
        task_id: str,
        payload: Dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 3,
        retry_delay: float = 5.0,
        delay_seconds: float = 0,
        deadline_seconds: Optional[float] = None,
        tags: Optional[Set[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> QueuedTask:
        """提交任务到队列"""
        with self._lock:
            if task_id in self._tasks:
                raise ValueError(f"Task {task_id} already exists")
            
            now = time.time()
            task = QueuedTask(
                priority=priority.value,
                created_at=now,
                task_id=task_id,
                payload=payload,
                status=TaskStatus.SCHEDULED if delay_seconds > 0 else TaskStatus.PENDING,
                max_retries=max_retries,
                retry_delay=retry_delay,
                scheduled_at=now + delay_seconds if delay_seconds > 0 else None,
                deadline=now + deadline_seconds if deadline_seconds else None,
                tags=tags or set(),
                metadata=metadata or {}
            )
            
            self._tasks[task_id] = task
            heapq.heappush(self._heap, task)
            self._persist()
            
            self._trigger('on_submit', task)
            return task
    
    def get_next(self, worker_id: str, timeout: float = 1.0) -> Optional[QueuedTask]:
        """获取下一个可执行任务"""
        with self._lock:
            if self._shutdown:
                return None
            
            now = time.time()
            
            # 检查堆顶任务
            while self._heap:
                task = self._heap[0]
                
                # 检查是否已取消或死亡
                if task.status in (TaskStatus.CANCELLED, TaskStatus.DEAD):
                    heapq.heappop(self._heap)
                    continue
                
                # 检查是否延迟执行
                if task.scheduled_at and now < task.scheduled_at:
                    return None
                
                # 检查是否超时
                if task.deadline and now > task.deadline:
                    task.status = TaskStatus.FAILED
                    task.error = "Deadline exceeded"
                    heapq.heappop(self._heap)
                    self._trigger('on_fail', task)
                    continue
                
                # 获取任务
                heapq.heappop(self._heap)
                task.status = TaskStatus.RUNNING
                task.assigned_to = worker_id
                task.started_at = now
                self._running[task_id] = task
                
                self._trigger('on_start', task)
                return task
            
            return None
    
    def complete(self, task_id: str, result: Any = None) -> bool:
        """标记任务完成"""
        with self._lock:
            task = self._running.pop(task_id, None) or self._tasks.get(task_id)
            if not task:
                return False
            
            task.status = TaskStatus.SUCCESS
            task.completed_at = time.time()
            task.result = result
            
            self._persist()
            self._trigger('on_complete', task)
            return True
    
    def fail(self, task_id: str, error: str) -> bool:
        """标记任务失败，触发重试或死信"""
        with self._lock:
            task = self._running.pop(task_id, None) or self._tasks.get(task_id)
            if not task:
                return False
            
            task.error = error
            task.retry_count += 1
            
            # 检查是否还有重试次数
            if task.retry_count < task.max_retries:
                # 指数退避
                delay = task.retry_delay * (2 ** (task.retry_count - 1))
                task.scheduled_at = time.time() + delay
                task.status = TaskStatus.RETRYING
                
                heapq.heappush(self._heap, task)
                self._persist()
                self._trigger('on_retry', task)
            else:
                # 进入死信队列
                task.status = TaskStatus.DEAD
                self._dead_letter.append(task)
                if len(self._dead_letter) > self._max_dead_letter:
                    self._dead_letter.pop(0)
                self._persist()
                self._trigger('on_dead', task)
            
            return True
    
    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            
            if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.DEAD):
                return False
            
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            
            # 如果在运行中，需要外部处理取消信号
            if task_id in self._running:
                del self._running[task_id]
            
            self._persist()
            return True
    
    def get_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return self._task_to_dict(task)
    
    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        tags: Optional[Set[str]] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """列出任务"""
        with self._lock:
            tasks = list(self._tasks.values())
            
            if status:
                tasks = [t for t in tasks if t.status == status]
            if tags:
                tasks = [t for t in tasks if tags & t.tags]
            
            tasks.sort(key=lambda t: t.created_at, reverse=True)
            return [self._task_to_dict(t) for t in tasks[:limit]]
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取队列指标"""
        with self._lock:
            status_counts = {}
            for task in self._tasks.values():
                status_counts[task.status.value] = status_counts.get(task.status.value, 0) + 1
            
            return {
                "total_tasks": len(self._tasks),
                "pending": len(self._heap),
                "running": len(self._running),
                "dead_letter": len(self._dead_letter),
                "by_status": status_counts,
                "avg_wait_time": self._calc_avg_wait(),
                "avg_process_time": self._calc_avg_process(),
            }
    
    def retry_dead(self, task_id: Optional[str] = None) -> bool:
        """重试死信队列中的任务"""
        with self._lock:
            if task_id:
                for i, task in enumerate(self._dead_letter):
                    if task.task_id == task_id:
                        task = self._dead_letter.pop(i)
                        task.status = TaskStatus.PENDING
                        task.retry_count = 0
                        task.error = None
                        heapq.heappush(self._heap, task)
                        self._persist()
                        return True
                return False
            else:
                # 重试所有死信
                for task in self._dead_letter:
                    task.status = TaskStatus.PENDING
                    task.retry_count = 0
                    task.error = None
                    heapq.heappush(self._heap, task)
                self._dead_letter.clear()
                self._persist()
                return True
    
    def on(self, event: str, callback: Callable):
        """注册事件回调"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def shutdown(self, wait: bool = True, timeout: float = 30.0):
        """关闭队列"""
        self._shutdown = True
        if wait and self._running:
            start = time.time()
            while self._running and time.time() - start < timeout:
                time.sleep(0.1)
    
    def _trigger(self, event: str, task: QueuedTask):
        """触发事件回调"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(task)
            except Exception as e:
                print(f"[TaskQueue] Callback error: {e}")
    
    def _task_to_dict(self, task: QueuedTask) -> Dict[str, Any]:
        """任务转字典"""
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "priority": task.priority,
            "payload": task.payload,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
            "assigned_to": task.assigned_to,
            "error": task.error,
            "result": task.result,
            "tags": list(task.tags),
            "metadata": task.metadata,
        }
    
    def _calc_avg_wait(self) -> float:
        """计算平均等待时间"""
        waits = []
        for task in self._tasks.values():
            if task.started_at and task.created_at:
                waits.append(task.started_at - task.created_at)
        return sum(waits) / len(waits) if waits else 0.0
    
    def _calc_avg_process(self) -> float:
        """计算平均处理时间"""
        times = []
        for task in self._tasks.values():
            if task.completed_at and task.started_at:
                times.append(task.completed_at - task.started_at)
        return sum(times) / len(times) if times else 0.0
    
    def _persist(self):
        """持久化到磁盘"""
        if not self._storage_path:
            return
        
        try:
            data = {
                "tasks": [self._task_to_dict(t) for t in self._tasks.values()],
                "dead_letter": [self._task_to_dict(t) for t in self._dead_letter],
                "saved_at": time.time(),
            }
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            print(f"[TaskQueue] Persist error: {e}")
    
    def _load_from_disk(self):
        """从磁盘加载"""
        if not self._storage_path or not self._storage_path.exists():
            return
        
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            
            for t in data.get("tasks", []):
                task = QueuedTask(
                    priority=t["priority"],
                    created_at=t["created_at"],
                    task_id=t["task_id"],
                    payload=t.get("payload", {}),
                    status=TaskStatus(t.get("status", "pending")),
                    max_retries=t.get("max_retries", 3),
                    retry_count=t.get("retry_count", 0),
                    assigned_to=t.get("assigned_to"),
                    started_at=t.get("started_at"),
                    completed_at=t.get("completed_at"),
                    error=t.get("error"),
                    result=t.get("result"),
                    tags=set(t.get("tags", [])),
                    metadata=t.get("metadata", {}),
                )
                self._tasks[task.task_id] = task
                if task.status in (TaskStatus.PENDING, TaskStatus.RETRYING):
                    heapq.heappush(self._heap, task)
                elif task.status == TaskStatus.RUNNING:
                    self._running[task.task_id] = task
            
            for t in data.get("dead_letter", []):
                task = QueuedTask(
                    priority=t["priority"],
                    created_at=t["created_at"],
                    task_id=t["task_id"],
                    payload=t.get("payload", {}),
                    status=TaskStatus.DEAD,
                )
                self._dead_letter.append(task)
            
            print(f"[TaskQueue] Loaded {len(self._tasks)} tasks from disk")
        except Exception as e:
            print(f"[TaskQueue] Load error: {e}")


# 全局队列实例
_global_queue: Optional[TaskQueue] = None


def get_task_queue(storage_path: Optional[Path] = None) -> TaskQueue:
    """获取全局任务队列"""
    global _global_queue
    if _global_queue is None:
        _global_queue = TaskQueue(storage_path)
    return _global_queue
