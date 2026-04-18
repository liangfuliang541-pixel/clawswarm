"""
metrics.py — 性能指标收集与导出
支持 Prometheus 格式、时序数据、告警规则
"""

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
import threading
import statistics


class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class MetricValue:
    """指标值"""
    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class HistogramBucket:
    """直方图桶"""
    upper_bound: float
    count: int


class Counter:
    """计数器（只增不减）"""
    
    def __init__(self, name: str, description: str = "", labels: Optional[List[str]] = None):
        self.name = name
        self.description = description
        self.label_names = labels or []
        self._values: Dict[tuple, float] = defaultdict(float)
        self._lock = threading.Lock()
    
    def inc(self, amount: float = 1, **labels):
        """增加计数"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            self._values[key] += amount
    
    def get(self, **labels) -> float:
        """获取当前值"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            return self._values[key]
    
    def collect(self) -> List[MetricValue]:
        """收集所有值"""
        with self._lock:
            return [
                MetricValue(value=v, timestamp=time.time(), labels=dict(zip(self.label_names, k)))
                for k, v in self._values.items()
            ]


class Gauge:
    """仪表盘（可增可减）"""
    
    def __init__(self, name: str, description: str = "", labels: Optional[List[str]] = None):
        self.name = name
        self.description = description
        self.label_names = labels or []
        self._values: Dict[tuple, float] = defaultdict(float)
        self._lock = threading.Lock()
    
    def set(self, value: float, **labels):
        """设置值"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            self._values[key] = value
    
    def inc(self, amount: float = 1, **labels):
        """增加"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            self._values[key] += amount
    
    def dec(self, amount: float = 1, **labels):
        """减少"""
        self.inc(-amount, **labels)
    
    def get(self, **labels) -> float:
        """获取当前值"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            return self._values[key]
    
    def collect(self) -> List[MetricValue]:
        """收集所有值"""
        with self._lock:
            return [
                MetricValue(value=v, timestamp=time.time(), labels=dict(zip(self.label_names, k)))
                for k, v in self._values.items()
            ]


class Histogram:
    """直方图（分布统计）"""
    
    def __init__(
        self,
        name: str,
        description: str = "",
        labels: Optional[List[str]] = None,
        buckets: Optional[List[float]] = None
    ):
        self.name = name
        self.description = description
        self.label_names = labels or []
        self.buckets = buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
        self._values: Dict[tuple, List[float]] = defaultdict(list)
        self._lock = threading.Lock()
    
    def observe(self, value: float, **labels):
        """观察值"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            self._values[key].append(value)
            # 限制存储数量，防止内存溢出
            if len(self._values[key]) > 10000:
                self._values[key] = self._values[key][-5000:]
    
    def get_buckets(self, **labels) -> List[HistogramBucket]:
        """获取桶分布"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            values = self._values[key]
        
        buckets = []
        for upper in self.buckets:
            count = sum(1 for v in values if v <= upper)
            buckets.append(HistogramBucket(upper_bound=upper, count=count))
        
        # +Inf 桶
        buckets.append(HistogramBucket(upper_bound=float('inf'), count=len(values)))
        return buckets
    
    def get_sum_count(self, **labels) -> tuple[float, int]:
        """获取总和和数量"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            values = self._values[key]
            return sum(values), len(values)


class Summary:
    """摘要（滑动窗口统计）"""
    
    def __init__(
        self,
        name: str,
        description: str = "",
        labels: Optional[List[str]] = None,
        quantiles: Optional[List[float]] = None,
        max_age: float = 600  # 10分钟窗口
    ):
        self.name = name
        self.description = description
        self.label_names = labels or []
        self.quantiles = quantiles or [0.5, 0.9, 0.95, 0.99]
        self.max_age = max_age
        self._values: Dict[tuple, List[tuple[float, float]]] = defaultdict(list)  # (value, timestamp)
        self._lock = threading.Lock()
    
    def observe(self, value: float, **labels):
        """观察值"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        now = time.time()
        with self._lock:
            self._values[key].append((value, now))
            # 清理过期数据
            cutoff = now - self.max_age
            self._values[key] = [(v, t) for v, t in self._values[key] if t > cutoff]
    
    def get_quantiles(self, **labels) -> Dict[float, float]:
        """获取分位数"""
        key = tuple(labels.get(k, "") for k in self.label_names)
        now = time.time()
        cutoff = now - self.max_age
        
        with self._lock:
            values = [v for v, t in self._values[key] if t > cutoff]
        
        if not values:
            return {q: 0.0 for q in self.quantiles}
        
        values.sort()
        result = {}
        for q in self.quantiles:
            idx = int(len(values) * q)
            idx = min(idx, len(values) - 1)
            result[q] = values[idx]
        return result


class MetricsRegistry:
    """指标注册表"""
    
    def __init__(self):
        self._metrics: Dict[str, Any] = {}
        self._lock = threading.Lock()
    
    def register(self, metric):
        """注册指标"""
        with self._lock:
            self._metrics[metric.name] = metric
        return metric
    
    def counter(self, name: str, description: str = "", labels: Optional[List[str]] = None) -> Counter:
        """创建或获取计数器"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Counter(name, description, labels)
            return self._metrics[name]
    
    def gauge(self, name: str, description: str = "", labels: Optional[List[str]] = None) -> Gauge:
        """创建或获取仪表盘"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Gauge(name, description, labels)
            return self._metrics[name]
    
    def histogram(self, name: str, description: str = "", labels: Optional[List[str]] = None, buckets: Optional[List[float]] = None) -> Histogram:
        """创建或获取直方图"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Histogram(name, description, labels, buckets)
            return self._metrics[name]
    
    def summary(self, name: str, description: str = "", labels: Optional[List[str]] = None) -> Summary:
        """创建或获取摘要"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Summary(name, description, labels)
            return self._metrics[name]
    
    def to_prometheus(self) -> str:
        """导出 Prometheus 格式"""
        lines = []
        
        with self._lock:
            for name, metric in self._metrics.items():
                lines.append(f"# HELP {name} {metric.description}")
                lines.append(f"# TYPE {name} {self._get_type(metric)}")
                
                if isinstance(metric, Counter):
                    for mv in metric.collect():
                        label_str = self._format_labels(mv.labels)
                        lines.append(f"{name}{label_str} {mv.value}")
                
                elif isinstance(metric, Gauge):
                    for mv in metric.collect():
                        label_str = self._format_labels(mv.labels)
                        lines.append(f"{name}{label_str} {mv.value}")
                
                elif isinstance(metric, Histogram):
                    # 桶
                    for label_key in metric._values.keys():
                        labels = dict(zip(metric.label_names, label_key))
                        buckets = metric.get_buckets(**labels)
                        for b in buckets:
                            label_str = self._format_labels({**labels, "le": str(b.upper_bound)})
                            lines.append(f"{name}_bucket{label_str} {b.count}")
                    # 总和
                    for label_key in metric._values.keys():
                        labels = dict(zip(metric.label_names, label_key))
                        s, c = metric.get_sum_count(**labels)
                        label_str = self._format_labels(labels)
                        lines.append(f"{name}_sum{label_str} {s}")
                        lines.append(f"{name}_count{label_str} {c}")
                
                elif isinstance(metric, Summary):
                    for label_key in metric._values.keys():
                        labels = dict(zip(metric.label_names, label_key))
                        quantiles = metric.get_quantiles(**labels)
                        for q, v in quantiles.items():
                            label_str = self._format_labels({**labels, "quantile": str(q)})
                            lines.append(f"{name}{label_str} {v}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """导出字典格式"""
        result = {}
        with self._lock:
            for name, metric in self._metrics.items():
                if isinstance(metric, (Counter, Gauge)):
                    result[name] = {
                        "type": self._get_type(metric),
                        "values": [
                            {"value": mv.value, "labels": mv.labels, "timestamp": mv.timestamp}
                            for mv in metric.collect()
                        ]
                    }
                elif isinstance(metric, Histogram):
                    result[name] = {
                        "type": "histogram",
                        "buckets": {k: metric.get_buckets(**dict(zip(metric.label_names, k))) for k in metric._values.keys()}
                    }
        return result
    
    def _get_type(self, metric) -> str:
        """获取指标类型字符串"""
        if isinstance(metric, Counter):
            return "counter"
        elif isinstance(metric, Gauge):
            return "gauge"
        elif isinstance(metric, Histogram):
            return "histogram"
        elif isinstance(metric, Summary):
            return "summary"
        return "unknown"
    
    def _format_labels(self, labels: Dict[str, str]) -> str:
        """格式化标签"""
        if not labels:
            return ""
        items = [f'{k}="{v}"' for k, v in labels.items()]
        return "{" + ",".join(items) + "}"


# 全局注册表
_registry: Optional[MetricsRegistry] = None


def get_metrics_registry() -> MetricsRegistry:
    """获取全局指标注册表"""
    global _registry
    if _registry is None:
        _registry = MetricsRegistry()
    return _registry


# 预定义常用指标
def init_default_metrics():
    """初始化默认指标"""
    r = get_metrics_registry()
    
    # 任务指标
    r.counter("clawswarm_tasks_total", "Total tasks", ["status", "type"])
    r.histogram("clawswarm_task_duration_seconds", "Task duration", ["type"])
    r.gauge("clawswarm_tasks_active", "Active tasks")
    
    # 节点指标
    r.gauge("clawswarm_nodes_total", "Total nodes", ["status"])
    r.counter("clawswarm_node_executions_total", "Node executions", ["node_id", "status"])
    
    # 系统指标
    r.gauge("clawswarm_memory_bytes", "Memory usage")
    r.gauge("clawswarm_cpu_percent", "CPU usage")
    r.counter("clawswarm_requests_total", "HTTP requests", ["method", "endpoint", "status"])
    r.histogram("clawswarm_request_duration_seconds", "Request duration", ["endpoint"])
