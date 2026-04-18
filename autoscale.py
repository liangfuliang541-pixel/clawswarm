"""
autoscale.py — 自动扩缩容
基于负载和队列深度自动调整 Agent 池大小
"""

import time
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from enum import Enum


class ScaleDirection(Enum):
    UP = "up"
    DOWN = "down"
    NONE = "none"


class ScalePolicy:
    """扩缩容策略"""
    def __init__(
        self,
        min_nodes: int = 1,
        max_nodes: int = 10,
        scale_up_threshold: float = 0.7,     # 队列使用率 > 70% 扩容
        scale_down_threshold: float = 0.2,   # 队列使用率 < 20% 缩容
        cooldown_up: float = 30.0,           # 扩容冷却时间(秒)
        cooldown_down: float = 120.0,         # 缩容冷却时间(秒)
        scale_step: int = 1,                 # 每次扩缩步长
        metrics_window: float = 60.0,        # 指标窗口(秒)
    ):
        self.min_nodes = min_nodes
        self.max_nodes = max_nodes
        self.scale_up_threshold = scale_up_threshold
        self.scale_down_threshold = scale_down_threshold
        self.cooldown_up = cooldown_up
        self.cooldown_down = cooldown_down
        self.scale_step = scale_step
        self.metrics_window = metrics_window


@dataclass
class PoolState:
    """Agent 池当前状态"""
    current_size: int
    desired_size: int
    last_scale_up: float = 0
    last_scale_down: float = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0


@dataclass
class ScaleEvent:
    """扩缩容事件"""
    timestamp: float
    direction: ScaleDirection
    from_size: int
    to_size: int
    reason: str


class AutoScaler:
    """自动扩缩容管理器"""
    
    def __init__(
        self,
        pool_name: str = "default",
        policy: Optional[ScalePolicy] = None,
        create_node_fn: Optional[Callable[[int], bool]] = None,
        remove_node_fn: Optional[Callable[[int], bool]] = None,
    ):
        self.pool_name = pool_name
        self.policy = policy or ScalePolicy()
        self._create_node = create_node_fn
        self._remove_node = remove_node_fn
        self._state = PoolState(current_size=1, desired_size=1)
        self._history: List[ScaleEvent] = []
        _running = False
        self._lock = threading.RLock()
        self._metrics_buffer: List[Dict] = []
        self._callbacks: List[Callable[[ScaleEvent], None]] = []
    
    def submit_metric(self, metric: Dict):
        """提交指标数据点"""
        now = time.time()
        # 清理过期数据
        cutoff = now - self.policy.metrics_window
        self._metrics_buffer = [m for m in self._metrics_buffer if m.get("timestamp", 0) > cutoff]
        self._metrics_buffer.append({**metric, "timestamp": now})
    
    def evaluate(self) -> Optional[ScaleEvent]:
        """评估是否需要扩缩容"""
        now = time.time()
        state = self._state
        
        # 计算队列使用率
        capacity = state.current_size
        if capacity <= 0:
            capacity = 1
        utilization = (state.pending_tasks + state.running_tasks) / capacity
        
        event = None
        
        # 检查扩容
        if (utilization > self.policy.scale_up_threshold
                and state.current_size < self.policy.max_nodes
                and now - state.last_scale_up >= self.policy.cooldown_up):
            new_size = min(state.current_size + self.policy.scale_step, self.policy.max_nodes)
            event = ScaleEvent(
                timestamp=now, direction=ScaleDirection.UP,
                from_size=state.current_size, to_size=new_size,
                reason=f"Utilization {utilization:.1%} > threshold {self.policy.scale_up_threshold:.0%}",
            )
            state.desired_size = new_size
            state.last_scale_up = now
        
        # 检查缩容
        elif (utilization < self.policy.scale_down_threshold
              and state.current_size > self.policy.min_nodes
              and now - state.last_scale_down >= self.policy.cooldown_down
              and state.current_size > 1):
            new_size = max(state.current_size - self.policy.scale_step, self.policy.min_nodes)
            event = ScaleEvent(
                timestamp=now, direction=ScaleDirection.DOWN,
                from_size=state.current_size, to_size=new_size,
                reason=f"Utilization {utilization:.1%} < threshold {self.policy.scale_down_threshold:.0%}",
            )
            state.desired_size = new_size
            state.last_scale_down = now
        
        if event:
            self._history.append(event)
            for cb in self._callbacks:
                try:
                    cb(event)
                except Exception:
                    pass
        
        return event
    
    def apply_scaling(self) -> bool:
        """执行扩缩容决策（实际创建/销毁节点）"""
        state = self._state
        if state.current_size == state.desired_size:
            return False
        
        diff = state.desired_size - state.current_size
        
        if diff > 0 and self._create_node:
            # 扩容
            success = self._create_node(diff)
            if success:
                state.current_size = state.desired_size
        elif diff < 0 and self._remove_node:
            # 缩容
            success = self._remove_node(-diff)
            if success:
                state.current_size = state.desired_size
                state.desired_size = state.current_size  # 同步
        
        return success
    
    def update_pool_state(self, current_size: int, pending: int = 0,
                            running: int = 0, cpu: float = 0.0, memory: float = 0.0):
        """更新池状态"""
        with self._lock:
            self._state.current_size = current_size
            self._state.pending_tasks = pending
            self._state.running_tasks = running
            self._state.cpu_usage = cpu
            self._state.memory_usage = memory
    
    def get_state(self) -> Dict:
        with self._lock:
            return {
                "pool_name": self.pool_name,
                "current_size": self._state.current_size,
                "desired_size": self._state.desired_size,
                "min_nodes": self.policy.min_nodes,
                "max_nodes": self.policy.max_nodes,
                "pending_tasks": self._state.pending_tasks,
                "running_tasks": self._state.running_tasks,
                "last_scale_up": self._state.last_scale_up,
                "last_scale_down": self._state.last_scale_down,
                "scale_events_count": len(self._history),
            }
    
    def get_history(self, limit: int = 50) -> List[Dict]:
        """获取扩缩容历史"""
        events = self._history[-limit:]
        return [
            {
                "timestamp": e.timestamp,
                "direction": e.direction.value,
                "from_size": e.from_size,
                "to_size": e.to_size,
                "reason": e.reason,
            }
            for e in events
        ]
    
    def on_scale(self, callback: Callable[[ScaleEvent], None]):
        """注册扩缩容事件回调"""
        self._callbacks.append(callback)
    
    def set_policy(self, policy: ScalePolicy):
        """更新扩缩容策略"""
        self.policy = policy
    
    def start_periodic(self, interval: float = 15.0):
        """启动周期性评估"""
        def _loop():
            _running = True
            while _running:
                event = self.evaluate()
                if event:
                    self.apply_scaling()
                time.sleep(interval)
        self._running = True
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
    
    def stop_periodic(self):
        self._running = False
