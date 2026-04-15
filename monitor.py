"""
ClawSwarm Monitor - 监控与指标系统
负责：节点健康检查、性能指标、告警通知、日志聚合

功能：
- 节点心跳监控
- 任务执行统计
- 资源使用追踪
- 告警规则引擎
- 指标可视化
"""

import json
import os
import time
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import statistics

# psutil 是可选依赖
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ── 监控数据类型 ─────────────────────────────────────────────────────────

class MetricType(Enum):
    COUNTER = "counter"      # 计数器（只增不减）
    GAUGE = "gauge"          # 仪表（可增可减）
    HISTOGRAM = "histogram"  # 直方图
    TIMER = "timer"          # 计时器

class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

# ── 数据模型 ─────────────────────────────────────────────────────────────

@dataclass
class Metric:
    """指标数据点"""
    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime = field(default_factory=datetime.now)
    tags: Dict[str, str] = field(default_factory=dict)
    unit: str = ""

@dataclass
class Alert:
    """告警"""
    level: AlertLevel
    title: str
    message: str
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False

@dataclass
class NodeHealth:
    """节点健康状态"""
    node_id: str
    status: str  # online, stale, offline
    last_heartbeat: datetime
    uptime_seconds: float
    tasks_completed: int = 0
    tasks_failed: int = 0
    cpu_percent: float = 0
    memory_percent: float = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

# ── 指标收集器 ─────────────────────────────────────────────────────────────

class MetricsCollector:
    """指标收集器"""
    
    def __init__(self, retention_minutes: int = 60):
        self.retention_minutes = retention_minutes
        
        # 指标存储
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._timers: Dict[str, List[float]] = defaultdict(list)
        
        # 线程安全
        self._lock = threading.Lock()
    
    # ── 计数器 ─────────────────────────────────────────────────────────
    
    def inc(self, name: str, value: float = 1, tags: Dict[str, str] = None):
        """增加计数器"""
        key = self._make_key(name, tags)
        with self._lock:
            self._counters[key] += value
    
    def dec(self, name: str, value: float = 1, tags: Dict[str, str] = None):
        """减少计数器"""
        key = self._make_key(name, tags)
        with self._lock:
            self._counters[key] -= value
    
    def get_counter(self, name: str, tags: Dict[str, str] = None) -> float:
        """获取计数器值"""
        key = self._make_key(name, tags)
        with self._lock:
            return self._counters.get(key, 0)
    
    # ── 仪表 ─────────────────────────────────────────────────────────
    
    def set_gauge(self, name: str, value: float, tags: Dict[str, str] = None):
        """设置仪表值"""
        key = self._make_key(name, tags)
        with self._lock:
            self._gauges[key] = value
    
    def get_gauge(self, name: str, tags: Dict[str, str] = None) -> Optional[float]:
        """获取仪表值"""
        key = self._make_key(name, tags)
        with self._lock:
            return self._gauges.get(key)
    
    # ── 直方图 ─────────────────────────────────────────────────────────
    
    def observe(self, name: str, value: float, tags: Dict[str, str] = None):
        """记录观测值"""
        key = self._make_key(name, tags)
        with self._lock:
            self._histograms[key].append(value)
    
    def get_histogram_stats(self, name: str, tags: Dict[str, str] = None) -> Dict[str, float]:
        """获取直方图统计"""
        key = self._make_key(name, tags)
        with self._lock:
            values = list(self._histograms.get(key, []))
        
        if not values:
            return {}
        
        return {
            "count": len(values),
            "sum": sum(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "p50": self._percentile(values, 50),
            "p75": self._percentile(values, 75),
            "p90": self._percentile(values, 90),
            "p95": self._percentile(values, 95),
            "p99": self._percentile(values, 99),
        }
    
    def _percentile(self, values: List[float], p: float) -> float:
        """计算百分位数"""
        if not values:
            return 0
        sorted_values = sorted(values)
        idx = int(len(sorted_values) * p / 100)
        return sorted_values[min(idx, len(sorted_values) - 1)]
    
    # ── 计时器 ─────────────────────────────────────────────────────────
    
    def start_timer(self, name: str) -> float:
        """开始计时"""
        return time.time()
    
    def stop_timer(self, name: str, start_time: float, tags: Dict[str, str] = None):
        """停止计时并记录"""
        duration = time.time() - start_time
        self.observe(name, duration, tags)
        return duration
    
    # ── 工具 ─────────────────────────────────────────────────────────
    
    def _make_key(self, name: str, tags: Dict[str, str] = None) -> str:
        """生成指标键"""
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"
    
    def get_all(self) -> Dict[str, Any]:
        """获取所有指标"""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    k: self.get_histogram_stats(k) 
                    for k in self._histograms.keys()
                },
            }
    
    def reset(self):
        """重置所有指标"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._timers.clear()


# ── 节点监控器 ─────────────────────────────────────────────────────────────

class NodeMonitor:
    """节点健康监控器"""
    
    def __init__(
        self,
        stale_threshold: int = 60,
        offline_threshold: int = 300,
        check_interval: int = 10
    ):
        self.stale_threshold = stale_threshold
        self.offline_threshold = offline_threshold
        self.check_interval = check_interval
        
        # 节点状态存储
        self._nodes: Dict[str, NodeHealth] = {}
        self._heartbeats: Dict[str, datetime] = {}
        
        # 告警回调
        self._alert_callbacks: List[Callable[[Alert], None]] = []
        
        # 线程
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
    
    def start(self):
        """启动监控"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _monitor_loop(self):
        """监控循环"""
        while self._running:
            self._check_node_health()
            time.sleep(self.check_interval)
    
    def _check_node_health(self):
        """检查节点健康状态"""
        now = datetime.now()
        
        with self._lock:
            nodes_to_remove = []
            
            for node_id, last_heartbeat in self._heartbeats.items():
                age = (now - last_heartbeat).total_seconds()
                
                # 更新节点状态
                if node_id in self._nodes:
                    node = self._nodes[node_id]
                    
                    if age <= self.stale_threshold:
                        node.status = "online"
                    elif age <= self.offline_threshold:
                        node.status = "stale"
                    else:
                        node.status = "offline"
                        
                        # 触发告警
                        self._trigger_alert(
                            AlertLevel.ERROR,
                            "节点离线",
                            f"节点 {node_id} 已离线 {age:.0f} 秒",
                            node_id
                        )
    
    def register_alert_callback(self, callback: Callable[[Alert], None]):
        """注册告警回调"""
        self._alert_callbacks.append(callback)
    
    def _trigger_alert(self, level: AlertLevel, title: str, message: str, source: str):
        """触发告警"""
        alert = Alert(
            level=level,
            title=title,
            message=message,
            source=source
        )
        
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception:
                pass
    
    # ── 节点管理 ─────────────────────────────────────────────────────────
    
    def register_node(self, node_id: str, metadata: Dict[str, Any] = None):
        """注册节点"""
        with self._lock:
            self._nodes[node_id] = NodeHealth(
                node_id=node_id,
                status="online",
                last_heartbeat=datetime.now(),
                uptime_seconds=0,
                metadata=metadata or {}
            )
            self._heartbeats[node_id] = datetime.now()
    
    def heartbeat(self, node_id: str, metrics: Dict[str, Any] = None):
        """节点心跳"""
        now = datetime.now()
        
        with self._lock:
            self._heartbeats[node_id] = now
            
            if node_id in self._nodes:
                node = self._nodes[node_id]
                node.last_heartbeat = now
                node.status = "online"
                
                # 更新资源指标
                if metrics:
                    node.cpu_percent = metrics.get("cpu_percent", 0)
                    node.memory_percent = metrics.get("memory_percent", 0)
                    node.tasks_completed = metrics.get("tasks_completed", 0)
                    node.tasks_failed = metrics.get("tasks_failed", 0)
    
    def get_nodes(self) -> List[NodeHealth]:
        """获取所有节点状态"""
        with self._lock:
            return list(self._nodes.values())
    
    def get_node(self, node_id: str) -> Optional[NodeHealth]:
        """获取指定节点状态"""
        with self._lock:
            return self._nodes.get(node_id)
    
    def get_online_nodes(self) -> List[str]:
        """获取在线节点列表"""
        with self._lock:
            return [
                node_id for node_id, node in self._nodes.items()
                if node.status == "online"
            ]


# ── 系统资源监控 ─────────────────────────────────────────────────────────────

class SystemMonitor:
    """系统资源监控（需要 psutil）"""

    def __init__(self):
        if not HAS_PSUTIL:
            raise ImportError("psutil is required for SystemMonitor: pip install psutil")
        self._process = psutil.Process()
    
    def get_cpu_percent(self, interval: float = 0.1) -> float:
        """获取 CPU 使用率"""
        return psutil.cpu_percent(interval=interval)
    
    def get_memory_info(self) -> Dict[str, Any]:
        """获取内存信息"""
        mem = psutil.virtual_memory()
        return {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "percent": mem.percent,
        }
    
    def get_disk_info(self, path: str = ".") -> Dict[str, Any]:
        """获取磁盘信息"""
        disk = psutil.disk_usage(path)
        return {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        }
    
    def get_network_info(self) -> Dict[str, Any]:
        """获取网络信息"""
        net = psutil.net_io_counters()
        return {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }
    
    def get_process_info(self) -> Dict[str, Any]:
        """获取当前进程信息"""
        with self._process.oneshot():
            return {
                "pid": self._process.pid,
                "cpu_percent": self._process.cpu_percent(),
                "memory_percent": self._process.memory_percent(),
                "memory_info": self._process.memory_info()._asdict(),
                "num_threads": self._process.num_threads(),
                "create_time": self._process.create_time(),
            }
    
    def get_all(self) -> Dict[str, Any]:
        """获取所有系统指标"""
        return {
            "cpu": {
                "percent": self.get_cpu_percent(),
            },
            "memory": self.get_memory_info(),
            "disk": self.get_disk_info(),
            "network": self.get_network_info(),
            "process": self.get_process_info(),
            "timestamp": datetime.now().isoformat(),
        }


# ── 告警管理器 ─────────────────────────────────────────────────────────────

class AlertManager:
    """告警管理器"""
    
    def __init__(self):
        self._alerts: deque = deque(maxlen=1000)
        self._rules: List[Callable[[Alert], Optional[Alert]]] = []
        self._handlers: Dict[AlertLevel, List[Callable[[Alert], None]]] = {
            level: [] for level in AlertLevel
        }
    
    def add_rule(self, rule: Callable[[Alert], Optional[Alert]]):
        """添加告警规则"""
        self._rules.append(rule)
    
    def on(self, level: AlertLevel, handler: Callable[[Alert], None]):
        """注册告警处理"""
        self._handlers[level].append(handler)
    
    def trigger(self, alert: Alert):
        """触发告警"""
        # 应用规则
        for rule in self._rules:
            result = rule(alert)
            if result is None:
                return  # 被规则过滤
            alert = result
        
        # 存储告警
        self._alerts.append(alert)
        
        # 调用处理
        for handler in self._handlers.get(alert.level, []):
            try:
                handler(alert)
            except Exception:
                pass
    
    def get_alerts(
        self,
        level: AlertLevel = None,
        limit: int = 100,
        unacknowledged_only: bool = False
    ) -> List[Alert]:
        """获取告警列表"""
        alerts = list(self._alerts)
        
        if level:
            alerts = [a for a in alerts if a.level == level]
        
        if unacknowledged_only:
            alerts = [a for a in alerts if not a.acknowledged]
        
        return alerts[-limit:]
    
    def acknowledge(self, alert: Alert):
        """确认告警"""
        alert.acknowledged = True


# ── 监控服务 ─────────────────────────────────────────────────────────────

class MonitorService:
    """
    统一监控服务
    
    用法:
        monitor = MonitorService()
        monitor.start()
        
        # 记录指标
        monitor.record("tasks_completed", 1)
        monitor.record_gauge("active_nodes", 5)
        
        # 获取状态
        status = monitor.get_status()
        print(status)
    """
    
    def __init__(self):
        self.metrics = MetricsCollector()
        self.node_monitor = NodeMonitor()
        self.system_monitor = SystemMonitor() if HAS_PSUTIL else None
        self.alert_manager = AlertManager()
        
        self._running = False
    
    def start(self):
        """启动监控服务"""
        self.node_monitor.start()
        self._running = True
        
        # 注册默认告警
        self.node_monitor.register_alert_callback(
            lambda alert: self.alert_manager.trigger(alert)
        )
    
    def stop(self):
        """停止监控服务"""
        self.node_monitor.stop()
        self._running = False
    
    # ── 指标记录 ─────────────────────────────────────────────────────────
    
    def record(self, name: str, value: float = 1, tags: Dict[str, str] = None):
        """记录指标（自动识别类型）"""
        # 这里简单处理，实际可以更智能
        self.metrics.observe(name, value, tags)
    
    def record_gauge(self, name: str, value: float, tags: Dict[str, str] = None):
        """记录仪表值"""
        self.metrics.set_gauge(name, value, tags)
    
    def record_counter(self, name: str, value: float = 1, tags: Dict[str, str] = None):
        """记录计数器"""
        self.metrics.inc(name, value, tags)
    
    def start_timer(self, name: str) -> float:
        """开始计时"""
        return self.metrics.start_timer(name)
    
    def stop_timer(self, name: str, start_time: float, tags: Dict[str, str] = None):
        """停止计时"""
        return self.metrics.stop_timer(name, start_time, tags)
    
    # ── 节点管理 ─────────────────────────────────────────────────────────
    
    def register_node(self, node_id: str, metadata: Dict[str, Any] = None):
        """注册节点"""
        self.node_monitor.register_node(node_id, metadata)
    
    def node_heartbeat(self, node_id: str, metrics: Dict[str, Any] = None):
        """节点心跳"""
        self.node_monitor.heartbeat(node_id, metrics)
    
    # ── 状态查询 ─────────────────────────────────────────────────────────
    
    def get_status(self) -> Dict[str, Any]:
        """获取完整状态"""
        return {
            "running": self._running,
            "metrics": self.metrics.get_all(),
            "nodes": {
                "total": len(self.node_monitor._nodes),
                "online": len(self.node_monitor.get_online_nodes()),
                "list": [
                    {
                        "node_id": n.node_id,
                        "status": n.status,
                        "uptime": n.uptime_seconds,
                        "tasks_completed": n.tasks_completed,
                        "cpu": n.cpu_percent,
                        "memory": n.memory_percent,
                    }
                    for n in self.node_monitor.get_nodes()
                ]
            },
            "system": self.system_monitor.get_all() if self.system_monitor else {"status": "psutil not available"},
            "alerts": {
                "total": len(self.alert_manager._alerts),
                "unacknowledged": len(self.alert_manager.get_alerts(unacknowledged_only=True)),
            },
            "timestamp": datetime.now().isoformat(),
        }
    
    def get_metrics_prometheus(self) -> str:
        """获取 Prometheus 格式的指标"""
        lines = []
        
        # 计数器
        for name, value in self.metrics._counters.items():
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")
        
        # 仪表
        for name, value in self.metrics._gauges.items():
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        
        # 直方图
        for name in self.metrics._histograms.keys():
            stats = self.metrics.get_histogram_stats(name)
            if stats:
                lines.append(f"# TYPE {name} histogram")
                lines.append(f"{name}_count {stats['count']}")
                lines.append(f"{name}_sum {stats['sum']}")
        
        return "\n".join(lines)


# ── 便捷函数 ─────────────────────────────────────────────────────────────

# 全局监控实例
_monitor: Optional[MonitorService] = None

def get_monitor() -> MonitorService:
    """获取全局监控实例"""
    global _monitor
    if _monitor is None:
        _monitor = MonitorService()
        _monitor.start()
    return _monitor

def record_metric(name: str, value: float = 1, tags: Dict[str, str] = None):
    """快速记录指标"""
    get_monitor().record(name, value, tags)

def record_gauge(name: str, value: float, tags: Dict[str, str] = None):
    """快速记录仪表"""
    get_monitor().record_gauge(name, value, tags)


# ── 测试 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("Monitor 测试")
    print("=" * 50)
    
    # 创建监控服务
    monitor = MonitorService()
    monitor.start()
    
    # 注册节点
    monitor.register_node("node-1", {"capability": "web"})
    monitor.register_node("node-2", {"capability": "compute"})
    
    # 模拟心跳
    monitor.node_heartbeat("node-1", {
        "cpu_percent": 25.5,
        "memory_percent": 40.0,
        "tasks_completed": 10,
    })
    
    # 记录指标
    monitor.record_counter("tasks_completed")
    monitor.record_counter("tasks_completed")
    monitor.record_gauge("active_nodes", 2)
    
    # 计时
    start = monitor.start_timer("task_duration")
    time.sleep(0.1)
    monitor.stop_timer("task_duration", start)
    
    # 获取状态
    status = monitor.get_status()
    print("\n节点状态:")
    for node in status["nodes"]["list"]:
        print(f"  {node['node_id']}: {node['status']}")
    
    print(f"\n指标: {status['metrics']['counters']}")
    
    # Prometheus 格式
    print("\nPrometheus 格式:")
    print(monitor.get_metrics_prometheus())
    
    monitor.stop()
    print("\n测试完成!")
