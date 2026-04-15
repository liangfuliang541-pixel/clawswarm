"""
ClawSwarm - 可观察性模块 (OpenTelemetry 集成)

支持：
  - 分布式追踪（traces）：任务生命周期、Agent 调用链
  - 指标（metrics）：Prometheus 格式导出
  - 结构化日志（logs）：JSON 格式，集成标准 logger
  - 检查点事件（events）：审批通过/拒绝/超时

集成 OpenClaw 的 tracing（如果有的话），
也可以独立运行（不需要 OpenClaw）。

用法:
    from observability import tracer, metrics, emit_log, emit_event

    # 追踪任务执行
    with tracer.start_as_current_span("execute_task") as span:
        span.set_attribute("task_id", task_id)
        result = execute_task(task)
        span.set_status(span.STATUS_OK)

    # 记录指标
    metrics.increment("clawswarm.task.completed", tags={"node": node_id, "type": task_type})

    # 结构化日志
    emit_log("info", "Task completed", task_id=task_id, duration_ms=elapsed)

    # 事件
    emit_event("task.completed", task_id=task_id, result="success")
"""

import os, sys, time, json, logging, traceback
from datetime import datetime
from typing import Dict, Any, Optional, List
from collections import defaultdict
from threading import RLock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import LOGS_DIR

os.makedirs(LOGS_DIR, exist_ok=True)

# ── 检测 OpenTelemetry 可用性 ─────────────────────────────────────────────

try:
    from opentelemetry import trace, metrics as ot_metrics, logs
    from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.semconv.resource import ResourceAttributes
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

# ── 配置 ─────────────────────────────────────────────────────────────────

OTEL_ENABLED    = os.environ.get("CLAWSWARM_OTEL_ENABLED", "false").lower() == "true"
OTEL_ENDPOINT   = os.environ.get("CLAWSWARM_OTEL_ENDPOINT", "http://localhost:4317")
OTEL_SERVICE    = os.environ.get("CLAWSWARM_SERVICE_NAME", "clawswarm")
OTEL_ENV        = os.environ.get("CLAWSWARM_ENV", "development")

# ── Trace 追踪 ─────────────────────────────────────────────────────────

_tracer: Optional["trace.Tracer"] = None

def _init_tracer():
    global _tracer
    if not OTEL_AVAILABLE:
        _tracer = None
        return

    try:
        resource = Resource.create({
            ResourceAttributes.SERVICE_NAME: OTEL_SERVICE,
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: OTEL_ENV,
        })
        provider = TracerProvider(resource=resource)

        # 添加 Console exporter（调试用）
        if os.environ.get("CLAWSWARM_OTEL_CONSOLE", "false").lower() == "true":
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        # 添加 OTLP exporter（发送到 Jaeger/Tempo）
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace.exporter import OTLPSpanExporter
            otlp_exporter = OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        except ImportError:
            pass  # OTLP exporter 不可用，跳过

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(__name__)
    except Exception:
        _tracer = None

_init_tracer()


class NoOpSpan:
    """当 OpenTelemetry 不可用时的无操作 span"""
    STATUS_OK = type("STATUS_OK", (), {})()
    STATUS_ERROR = type("STATUS_ERROR", (), {})()

    def set_attribute(self, key, value): pass
    def set_status(self, status): pass
    def record_exception(self, exc): pass
    def add_event(self, name, attributes=None): pass
    def end(self): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass


class NoOpTracer:
    """当 OpenTelemetry 不可用时的无操作 tracer"""
    def start_as_current_span(self, name, **kwargs):
        return NoOpSpan()
    def start_span(self, name, **kwargs):
        return NoOpSpan()


def get_tracer():
    """获取 tracer 实例"""
    if _tracer is not None:
        return _tracer
    return NoOpTracer()


class SwallowTracer:
    """兼容接口：无论 OTEL 是否可用都能用"""
    def __init__(self):
        self._real = get_tracer()

    def start_as_current_span(self, name, **kwargs):
        return self._real.start_as_current_span(name, **kwargs)

    def span(self, name: str):
        return self._real.start_as_current_span(name)

    # 快捷方法
    def trace_task(self, task_id: str, task_type: str = None):
        span = self._real.start_as_current_span(f"task.{task_type or 'exec'}")
        span.set_attribute("task_id", task_id)
        if task_type:
            span.set_attribute("task_type", task_type)
        span.set_attribute("service", OTEL_SERVICE)
        return span


tracer = SwallowTracer()


# ── Metrics 指标 ────────────────────────────────────────────────────────

class MetricsCollector:
    """
    轻量指标收集器，支持 Prometheus 格式导出。
    不需要 OpenTelemetry 也能用。

    指标类型：
      Counter   — 累加计数（任务完成数、错误数）
      Gauge     — 当前值（活跃任务数、节点数）
      Histogram — 分布（任务耗时、等待时间）
    """

    def __init__(self):
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._tags: Dict[str, Dict[str, str]] = {}
        self._lock = RLock()

    def counter(self, name: str, value: float = 1.0, **tags) -> None:
        with self._lock:
            key = self._make_key(name, tags)
            self._counters[key] += value
            self._tags[key] = tags

    def gauge(self, name: str, value: float, **tags) -> None:
        with self._lock:
            key = self._make_key(name, tags)
            self._gauges[key] = value
            self._tags[key] = tags

    def histogram(self, name: str, value: float, **tags) -> None:
        with self._lock:
            key = self._make_key(name, tags)
            self._histograms[key].append(value)
            self._tags[key] = tags

    def _make_key(self, name: str, tags: dict) -> str:
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"

    def to_prometheus(self) -> str:
        """导出 Prometheus 格式"""
        lines = []
        ts = time.time()

        with self._lock:
            # Counters
            for key, value in self._counters.items():
                lines.append(f"# TYPE {key} counter")
                lines.append(f"{key} {value} {int(ts * 1000)}")

            # Gauges
            for key, value in self._gauges.items():
                lines.append(f"# TYPE {key} gauge")
                lines.append(f"{key} {value} {int(ts * 1000)}")

            # Histograms（简化为 summary）
            for key, values in self._histograms.items():
                if not values:
                    continue
                name = key.split("{")[0]
                vals = sorted(values)
                n = len(vals)
                lines.append(f"# TYPE {key} summary")
                lines.append(f"{key}_sum {sum(vals)} {int(ts * 1000)}")
                lines.append(f"{key}_count {n} {int(ts * 1000)}")
                for q in [0.5, 0.9, 0.99]:
                    idx = min(int(q * n), n - 1)
                    qkey = key.replace("}", f',quantile="{q}"}}')
                    lines.append(f"{qkey} {vals[idx]} {int(ts * 1000)}")

        return "\n".join(lines)

    def export_json(self) -> dict:
        """导出 JSON 格式"""
        with self._lock:
            return {
                "timestamp": datetime.now().isoformat(),
                "counters":  dict(self._counters),
                "gauges":    dict(self._gauges),
                "histograms": {k: {
                    "count": len(v),
                    "min": min(v) if v else 0,
                    "max": max(v) if v else 0,
                    "avg": sum(v) / len(v) if v else 0,
                } for k, v in self._histograms.items()},
            }


# 全局指标收集器
_metrics: Optional[MetricsCollector] = None

def get_metrics() -> MetricsCollector:
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics

# 快捷方法
def inc(name: str, value: float = 1.0, **tags):
    get_metrics().counter(name, value, **tags)

def set_gauge(name: str, value: float, **tags):
    get_metrics().gauge(name, value, **tags)

def observe(name: str, value: float, **tags):
    get_metrics().histogram(name, value, **tags)


# ── 结构化日志 ──────────────────────────────────────────────────────────

class StructuredLogger:
    """
    结构化日志：JSON 格式，写入文件 + stdout。
    自动添加 service / env / timestamp / trace_id。
    """

    def __init__(self, name: str = "clawswarm"):
        self.name = name
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    def log(self, level: str, msg: str, **extra):
        entry = {
            "ts":    datetime.now().isoformat(),
            "level": level.upper(),
            "msg":   msg,
            "svc":   self.name,
            "env":   OTEL_ENV,
            **extra,
        }
        # 尝试添加 trace_id
        try:
            if OTEL_AVAILABLE:
                span = trace.get_current_span()
                if span and span.get_span_context().is_valid:
                    entry["trace_id"] = format(span.get_span_context().trace_id, "032x")
                    entry["span_id"] = format(span.get_span_context().span_id, "016x")
        except Exception:
            pass

        getattr(self.logger, level.lower().replace("warn", "warning"))(json.dumps(entry, ensure_ascii=False))

    def debug(self, msg, **kw): self.log("DEBUG", msg, **kw)
    def info(self, msg, **kw):  self.log("INFO", msg, **kw)
    def warn(self, msg, **kw):  self.log("WARN", msg, **kw)
    def error(self, msg, **kw): self.log("ERROR", msg, **kw)

    def task_start(self, task_id: str, task_type: str = None, node: str = None):
        self.info("Task started", event="task.start", task_id=task_id,
                  task_type=task_type, node=node)

    def task_done(self, task_id: str, task_type: str = None, node: str = None,
                  duration_ms: float = None, result: str = None):
        self.info("Task completed", event="task.done", task_id=task_id,
                  task_type=task_type, node=node, duration_ms=duration_ms, result=result)
        inc("clawswarm.task.completed", task_type=task_type or "unknown",
            node=node or "unknown", result=result or "unknown")

    def task_fail(self, task_id: str, task_type: str = None, node: str = None,
                  error: str = None):
        self.error("Task failed", event="task.failed", task_id=task_id,
                   task_type=task_type, node=node, error=error)
        inc("clawswarm.task.failed", task_type=task_type or "unknown",
            node=node or "unknown")

    def checkpoint(self, checkpoint_id: str, task_id: str, action: str,
                   approver: str = None, reason: str = None):
        self.info(f"Checkpoint {action}", event=f"checkpoint.{action}",
                  checkpoint_id=checkpoint_id, task_id=task_id,
                  approver=approver, reason=reason)
        inc(f"clawswarm.checkpoint.{action}", task_type=task_id.split("_")[1] if "_" in task_id else "unknown")


# 全局 logger
log = StructuredLogger()


# ── 事件发射器 ──────────────────────────────────────────────────────────

class EventEmitter:
    """
    事件发射器：记录关键事件，供 WebSocket / Webhook 消费。
    """

    def __init__(self):
        self._handlers: List[callable] = []
        self._lock = RLock()

    def on(self, handler: callable):
        with self._lock:
            self._handlers.append(handler)

    def off(self, handler: callable):
        with self._lock:
            self._handlers.remove(handler)

    def emit(self, event_type: str, data: dict = None):
        event = {
            "type":    event_type,
            "ts":      datetime.now().isoformat(),
            "service": OTEL_SERVICE,
            "data":    data or {},
        }
        with self._lock:
            for handler in self._handlers:
                try:
                    handler(event)
                except Exception:
                    pass

    # 快捷方法
    def task_started(self, task_id: str, **kw):
        self.emit("task.started", {"task_id": task_id, **kw})

    def task_completed(self, task_id: str, result: Any = None, **kw):
        self.emit("task.completed", {"task_id": task_id, "result": str(result)[:500] if result else None, **kw})

    def task_failed(self, task_id: str, error: str = None, **kw):
        self.emit("task.failed", {"task_id": task_id, "error": error, **kw})

    def checkpoint_pending(self, checkpoint_id: str, task_id: str, **kw):
        self.emit("checkpoint.pending", {"checkpoint_id": checkpoint_id, "task_id": task_id, **kw})

    def checkpoint_decided(self, checkpoint_id: str, result: str, approver: str, **kw):
        self.emit("checkpoint.decided", {"checkpoint_id": checkpoint_id, "result": result, "approver": approver, **kw})

    def node_online(self, node_id: str, **kw):
        self.emit("node.online", {"node_id": node_id, **kw})

    def node_offline(self, node_id: str, **kw):
        self.emit("node.offline", {"node_id": node_id, **kw})


# 全局事件发射器
events = EventEmitter()


# ── Metrics HTTP 端点（供 Prometheus 拉取）───────────────────────────────

METRICS_FILE = os.path.join(LOGS_DIR, "metrics.prom")

def update_metrics_file():
    """将当前指标写入 Prometheus 文件（供 Prometheus 拉取）"""
    prom_text = get_metrics().to_prometheus()
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        f.write(prom_text)


# ── 自动打点装饰器 ───────────────────────────────────────────────────────

def traced(span_name: str = None, task_type_attr: str = None):
    """自动追踪函数执行"""
    def decorator(func):
        import functools
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = span_name or func.__name__
            with tracer.start_as_current_span(name) as span:
                try:
                    result = func(*args, **kwargs)
                    span.set_status(span.STATUS_OK)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(span.STATUS_ERROR)
                    raise
        return wrapper
    return decorator


# ── 初始化日志文件 Handler ─────────────────────────────────────────────

def _setup_file_log():
    log_file = os.path.join(LOGS_DIR, "clawswarm.jsonl")
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    lg = logging.getLogger("clawswarm")
    lg.addHandler(handler)

_setup_file_log()


# ── CLI ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ClawSwarm Observability")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("metrics", help="导出 Prometheus 格式指标")
    sub.add_parser("events", help="显示事件列表（最近 20 条）")
    sub.add_parser("summary", help="显示指标摘要")

    args = parser.parse_args(sys.argv[1:])

    if args.cmd == "metrics":
        print(get_metrics().to_prometheus())

    elif args.cmd == "events":
        log_file = os.path.join(LOGS_DIR, "clawswarm.jsonl")
        if os.path.exists(log_file):
            with open(log_file, encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-20:]:
                try:
                    event = json.loads(line.strip())
                    print(json.dumps(event, ensure_ascii=False))
                except Exception:
                    pass

    elif args.cmd == "summary":
        data = get_metrics().export_json()
        print(json.dumps(data, ensure_ascii=False, indent=2))

    else:
        print("ClawSwarm Observability CLI")
        print("  python observability.py metrics  # Prometheus 格式")
        print("  python observability.py events   # 最近事件")
        print("  python observability.py summary  # 指标摘要")
