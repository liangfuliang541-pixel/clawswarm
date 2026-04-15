"""
ClawSwarm Webhook 处理模块

支持：
- 任务事件 webhook
- 节点事件 webhook
- 自定义 webhook 规则
"""

import json
import hashlib
import hmac
import time
from datetime import datetime
from typing import Dict, List, Any, Callable, Optional
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import aiohttp

# ── 事件类型 ─────────────────────────────────────────────────────────

class EventType(str, Enum):
    # 任务事件
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TASK_TIMEOUT = "task.timeout"
    
    # 节点事件
    NODE_REGISTERED = "node.registered"
    NODE_HEARTBEAT = "node.heartbeat"
    NODE_OFFLINE = "node.offline"
    NODE_ONLINE = "node.online"
    
    # 系统事件
    SYSTEM_STARTED = "system.started"
    SYSTEM_STOPPED = "system.stopped"
    ERROR = "error"

# ── Webhook 配置 ─────────────────────────────────────────────────────────

@dataclass
class WebhookConfig:
    """Webhook 配置"""
    url: str
    secret: str = ""
    enabled: bool = True
    retry_count: int = 3
    retry_delay: float = 1.0
    timeout: float = 10.0
    headers: Dict[str, str] = field(default_factory=dict)

# ── Webhook 事件 ─────────────────────────────────────────────────────────

@dataclass
class WebhookEvent:
    """Webhook 事件"""
    event_type: EventType
    data: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = "clawswarm"
    id: str = field(default_factory=lambda: f"evt_{int(time.time()*1000)}")

# ── Webhook 发送器 ─────────────────────────────────────────────────────────

class WebhookSender:
    """
    Webhook 发送器
    
    用法:
        sender = WebhookSender()
        sender.add_webhook("https://example.com/webhook", secret="mysecret")
        sender.send(EventType.TASK_COMPLETED, {"task_id": "xxx", "result": "ok"})
    """
    
    def __init__(self):
        self._webhooks: List[WebhookConfig] = []
        self._handlers: Dict[EventType, List[Callable]] = {
            event: [] for event in EventType
        }
        
        # 统计
        self._stats = {
            "sent": 0,
            "failed": 0,
            "retries": 0
        }
    
    def add_webhook(self, url: str, secret: str = "", **kwargs):
        """添加 webhook"""
        config = WebhookConfig(url=url, secret=secret, **kwargs)
        self._webhooks.append(config)
    
    def remove_webhook(self, url: str):
        """移除 webhook"""
        self._webhooks = [w for w in self._webhooks if w.url != url]
    
    def on(self, event_type: EventType, handler: Callable):
        """注册事件处理器"""
        self._handlers[event_type].append(handler)
    
    async def send(
        self,
        event_type: EventType,
        data: Dict[str, Any],
        source: str = "clawswarm"
    ):
        """发送 webhook"""
        event = WebhookEvent(
            event_type=event_type,
            data=data,
            source=source
        )
        
        # 本地处理
        for handler in self._handlers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception:
                pass
        
        # 发送远程 webhook
        for webhook in self._webhooks:
            if not webhook.enabled:
                continue
            
            try:
                await self._send_webhook(webhook, event)
                self._stats["sent"] += 1
            except Exception:
                self._stats["failed"] += 1
    
    async def _send_webhook(self, webhook: WebhookConfig, event: WebhookEvent):
        """发送单个 webhook"""
        payload = json.dumps(event.__dict__, ensure_ascii=False, default=str)
        
        # 签名
        headers = {"Content-Type": "application/json", **webhook.headers}
        
        if webhook.secret:
            signature = self._generate_signature(payload, webhook.secret)
            headers["X-Signature"] = signature
        
        headers["X-Event-ID"] = event.id
        headers["X-Event-Type"] = event.event_type.value
        headers["X-Timestamp"] = event.timestamp
        
        # 重试
        last_error = None
        for attempt in range(webhook.retry_count):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        webhook.url,
                        data=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=webhook.timeout)
                    ) as resp:
                        if resp.status < 400:
                            return
                        last_error = f"HTTP {resp.status}"
            except asyncio.TimeoutError:
                last_error = "Timeout"
            except Exception as e:
                last_error = str(e)
            
            if attempt < webhook.retry_count - 1:
                self._stats["retries"] += 1
                await asyncio.sleep(webhook.retry_delay * (attempt + 1))
        
        raise Exception(f"Failed after {webhook.retry_count} attempts: {last_error}")
    
    def _generate_signature(self, payload: str, secret: str) -> str:
        """生成签名"""
        return hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
    
    def get_stats(self) -> Dict:
        """获取统计"""
        return {
            **self._stats,
            "webhooks": len(self._webhooks)
        }


# ── Webhook 规则引擎 ─────────────────────────────────────────────────

class WebhookRule:
    """Webhook 规则"""
    
    def __init__(
        self,
        event_type: EventType,
        condition: Callable[[WebhookEvent], bool] = None,
        action: Callable[[WebhookEvent], Any] = None
    ):
        self.event_type = event_type
        self.condition = condition
        self.action = action


class WebhookRuleEngine:
    """
    Webhook 规则引擎
    
    用法:
        engine = WebhookRuleEngine()
        
        # 添加规则
        @engine.rule(EventType.TASK_COMPLETED)
        def on_task_completed(event):
            if event.data.get("result"):
                send_notification(...)
    """
    
    def __init__(self):
        self._rules: List[WebhookRule] = []
        self._sender = WebhookSender()
    
    def rule(self, event_type: EventType):
        """装饰器：添加规则"""
        def decorator(func):
            rule = WebhookRule(
                event_type=event_type,
                action=func
            )
            self._rules.append(rule)
            return func
        return decorator
    
    def add_rule(self, rule: WebhookRule):
        """添加规则"""
        self._rules.append(rule)
    
    async def process(self, event: WebhookEvent):
        """处理事件"""
        for rule in self._rules:
            if rule.event_type != event.event_type:
                continue
            
            # 检查条件
            if rule.condition and not rule.condition(event):
                continue
            
            # 执行动作
            if rule.action:
                try:
                    if asyncio.iscoroutinefunction(rule.action):
                        await rule.action(event)
                    else:
                        rule.action(event)
                except Exception:
                    pass
        
        # 发送到远程 webhook
        await self._sender.send(event.event_type, event.data, event.source)
    
    @property
    def sender(self) -> WebhookSender:
        """获取发送器"""
        return self._sender


# ── 便捷函数 ─────────────────────────────────────────────────────────

# 全局 webhook 引擎
_webhook_engine: Optional[WebhookRuleEngine] = None

def get_webhook_engine() -> WebhookRuleEngine:
    """获取全局 webhook 引擎"""
    global _webhook_engine
    if _webhook_engine is None:
        _webhook_engine = WebhookRuleEngine()
    return _webhook_engine

def on_task_created(handler: Callable):
    """任务创建事件"""
    get_webhook_engine().on(EventType.TASK_CREATED, handler)

def on_task_completed(handler: Callable):
    """任务完成事件"""
    get_webhook_engine().on(EventType.TASK_COMPLETED, handler)

def on_task_failed(handler: Callable):
    """任务失败事件"""
    get_webhook_engine().on(EventType.TASK_FAILED, handler)

def on_node_offline(handler: Callable):
    """节点离线事件"""
    get_webhook_engine().on(EventType.NODE_OFFLINE, handler)


# ── 测试 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("Webhook 测试")
    print("=" * 50)
    
    import unittest.mock
    
    # 创建引擎
    engine = get_webhook_engine()
    
    # 添加 webhook（模拟）
    # engine.sender.add_webhook("https://example.com/webhook", secret="test")
    
    # 添加规则
    @engine.rule(EventType.TASK_COMPLETED)
    def handle_completed(event):
        print(f"✅ 任务完成: {event.data.get('task_id')}")
    
    # 模拟事件
    async def test():
        event = WebhookEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "test_001", "result": "OK"}
        )
        
        await engine.process(event)
        
        print(f"\n统计: {engine.sender.get_stats()}")
    
    asyncio.run(test())
    
    print("\n测试完成!")
