"""
ClawSwarm - Human-in-the-Loop 检查点系统

关键任务执行到关键节点时，暂停等待人工审批。

核心概念：
  Checkpoint  = 一个暂停点（审批/审查/确认）
  Approval    = 审批记录（批准/拒绝 + 原因）

工作流：
  1. Orchestrator 在关键节点调用 checkpoint.wait("task_id", "审批描述")
  2. 任务状态改为 "waiting_approval"，推送通知到人工
  3. 人工通过 CLI / Web API / Webhook 审批
  4. checkpoint 收到结果，任务继续或终止

支持的通知方式：
  - 文件（checkpoint/pending/ 目录，轮询）
  - Webhook（POST 回调）
  - OpenClaw 消息（nodes.notify，通过配置的 channel）
  - WebSocket（实时推送，v0.6）

用法:
    from checkpoint import Checkpoint, CheckpointManager, HITL_POLICY

    # 全局审批策略
    HITL_POLICY.set_always_approve()      # 开发模式：自动批准
    HITL_POLICY.set_always_require()       # 生产模式：必须人工审批
    HITL_POLICY.set_require_above_priority(5)  # 优先级 >= 5 才审批

    # 任务执行中触发检查点
    chk = Checkpoint("t_001", "confirm_code_review", "确认发布代码？")
    result = chk.wait(timeout=300)  # 等待 5 分钟
    if result.approved:
        proceed()
    else:
        abort()
"""

import os, sys, json, time, uuid, threading, asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Literal, List, Dict, Any, Callable
from enum import Enum
from collections import defaultdict
from threading import RLock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, ensure_dirs
from models import TaskStatus

# ── 目录 ─────────────────────────────────────────────────────────────────

CHECKPOINT_DIR = os.path.join(BASE_DIR, "checkpoint")
PENDING_DIR    = os.path.join(CHECKPOINT_DIR, "pending")   # 等待审批
APPROVED_DIR   = os.path.join(CHECKPOINT_DIR, "approved") # 已批准
REJECTED_DIR   = os.path.join(CHECKPOINT_DIR, "rejected") # 已拒绝
POLICY_FILE    = os.path.join(CHECKPOINT_DIR, "policy.json")

ensure_dirs()
for d in [PENDING_DIR, APPROVED_DIR, REJECTED_DIR]:
    os.makedirs(d, exist_ok=True)

# ── 枚举 ─────────────────────────────────────────────────────────────────

class CheckpointType(Enum):
    APPROVAL = "approval"    # 需要明确批准
    REVIEW   = "review"       # 需要人工审查
    CONFIRM  = "confirm"     # 确认执行
    ESCALATE = "escalate"    # 升级处理

class ApprovalResult(Enum):
    APPROVED  = "approved"
    REJECTED  = "rejected"
    TIMEOUT   = "timeout"
    SKIPPED   = "skipped"


# ── 数据模型 ─────────────────────────────────────────────────────────────

@dataclass
class Checkpoint:
    id:          str
    task_id:     str
    description: str
    type:        CheckpointType = CheckpointType.APPROVAL
    created_at:  str = field(default_factory=lambda: datetime.now().isoformat())
    approver:   str = "human"
    metadata:    Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "task_id":     self.task_id,
            "description": self.description,
            "type":        self.type.value,
            "created_at":  self.created_at,
            "approver":    self.approver,
            "metadata":    self.metadata,
        }

    def to_file(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


@dataclass
class ApprovalRecord:
    checkpoint_id: str
    result:        ApprovalResult
    approver:     str = "human"
    reason:       str = ""
    decided_at:   str = field(default_factory=lambda: datetime.now().isoformat())
    latency_ms:   float = 0.0

    def to_dict(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "result":       self.result.value,
            "approver":     self.approver,
            "reason":       self.reason,
            "decided_at":   self.decided_at,
            "latency_ms":   self.latency_ms,
        }


# ── 审批策略 ─────────────────────────────────────────────────────────────

class HITLPolicy:
    """
    全局审批策略。

    用法:
        HITL_POLICY.set_always_approve()           # 开发：自动批准
        HITL_POLICY.set_always_require()          # 生产：必须审批
        HITL_POLICY.set_require_above_priority(5)  # 优先级 >= 5 才审批
        HITL_POLICY.set_by_task_type({"code": "require", "fetch": "skip"})
    """

    def __init__(self):
        self._mode: Literal["always_approve", "always_require", "by_priority",
                            "by_task_type", "by_config"] = "always_approve"
        self._priority_threshold: int = 10
        self._task_type_config: Dict[str, str] = {}
        self._lock = RLock()
        self._listeners: List[Callable[["ApprovalRecord"], None]] = []
        self._load()

    def _load(self):
        if os.path.exists(POLICY_FILE):
            try:
                with open(POLICY_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                self._mode = data.get("mode", "always_approve")
                self._priority_threshold = data.get("priority_threshold", 10)
                self._task_type_config = data.get("task_type_config", {})
            except Exception:
                pass

    def save(self):
        data = {
            "mode": self._mode,
            "priority_threshold": self._priority_threshold,
            "task_type_config": self._task_type_config,
        }
        with open(POLICY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def should_require(self, task_type: str = None, priority: int = None) -> bool:
        with self._lock:
            if self._mode == "always_approve":
                return False
            elif self._mode == "always_require":
                return True
            elif self._mode == "by_priority":
                return priority is not None and priority >= self._priority_threshold
            elif self._mode == "by_task_type":
                if task_type is None:
                    return False
                action = self._task_type_config.get(task_type, "skip")
                return action == "require"
        return False

    def get_decision(self, checkpoint: Checkpoint) -> ApprovalResult:
        """自动决策（当 should_require = False 时）"""
        with self._lock:
            mode = self._mode

        if mode == "always_approve":
            return ApprovalResult.APPROVED
        return ApprovalResult.SKIPPED  # 未触发审批，返回跳过

    def set_always_approve(self):
        with self._lock:
            self._mode = "always_approve"
        self.save()

    def set_always_require(self):
        with self._lock:
            self._mode = "always_require"
        self.save()

    def set_require_above_priority(self, threshold: int = 5):
        with self._lock:
            self._mode = "by_priority"
            self._priority_threshold = threshold
        self.save()

    def set_by_task_type(self, config: Dict[str, str]):
        """设置按任务类型的策略: {"code": "require", "fetch": "skip", "report": "require"}"""
        with self._lock:
            self._mode = "by_task_type"
            self._task_type_config = config
        self.save()

    def add_listener(self, callback: Callable[[ApprovalRecord], None]):
        """添加审批结果监听器（用于通知）"""
        self._listeners.append(callback)

    def notify(self, record: ApprovalRecord):
        for cb in self._listeners:
            try:
                cb(record)
            except Exception:
                pass


# 全局策略单例
HITL_POLICY = HITLPolicy()


# ── 检查点管理器 ──────────────────────────────────────────────────────────

class CheckpointManager:
    """
    全局检查点管理器。

    用法:
        mgr = CheckpointManager()
        mgr.create("t_001", "confirm", "确认发布？")
        result = mgr.wait("chk_xxx", timeout=300)
    """

    def __init__(self):
        self._pending: Dict[str, Checkpoint] = {}
        self._decisions: Dict[str, ApprovalRecord] = {}
        self._lock = RLock()
        self._events: Dict[str, threading.Event] = {}

    def create(
        self,
        task_id: str,
        checkpoint_type: CheckpointType,
        description: str,
        metadata: Dict = None,
    ) -> Checkpoint:
        """
        创建检查点。根据策略决定是真正暂停还是自动批准。
        """
        chk_id = f"chk_{int(time.time()*1000)}"
        checkpoint = Checkpoint(
            id=chk_id,
            task_id=task_id,
            description=description,
            type=checkpoint_type,
            metadata=metadata or {},
        )

        with self._lock:
            self._pending[chk_id] = checkpoint
            self._events[chk_id] = threading.Event()

        # 检查是否需要真正等待
        task_type = metadata.get("task_type") if metadata else None
        priority = metadata.get("priority", 0) if metadata else 0

        if HITL_POLICY.should_require(task_type=task_type, priority=priority):
            # 真实等待：写入 pending 目录，触发通知
            checkpoint.to_file(os.path.join(PENDING_DIR, f"{chk_id}.json"))
            self._notify_approvers(checkpoint)
        else:
            # 自动批准
            decision = ApprovalRecord(
                checkpoint_id=chk_id,
                result=ApprovalResult.APPROVED,
                approver="auto_policy",
                reason=f"Policy: {HITL_POLICY._mode} (task_type={task_type}, priority={priority})",
                latency_ms=0.0,
            )
            with self._lock:
                self._decisions[chk_id] = decision
            HITL_POLICY.notify(decision)

        return checkpoint

    def wait(self, checkpoint_id: str, timeout: float = 300.0) -> ApprovalRecord:
        """
        等待检查点审批结果。
        timeout=0 表示无限等待。
        """
        with self._lock:
            if checkpoint_id in self._decisions:
                return self._decisions[checkpoint_id]
            evt = self._events.get(checkpoint_id)

        if evt is None:
            return ApprovalRecord(
                checkpoint_id=checkpoint_id,
                result=ApprovalResult.SKIPPED,
                reason="No checkpoint found",
            )

        if timeout > 0:
            arrived = evt.wait(timeout=timeout)
            if not arrived:
                # 超时
                decision = ApprovalRecord(
                    checkpoint_id=checkpoint_id,
                    result=ApprovalResult.TIMEOUT,
                    reason=f"Timeout after {timeout}s",
                    latency_ms=timeout * 1000,
                )
        else:
            evt.wait()
            with self._lock:
                decision = self._decisions.get(checkpoint_id,
                    ApprovalRecord(checkpoint_id=checkpoint_id, result=ApprovalResult.SKIPPED))

        return decision

    def approve(self, checkpoint_id: str, approver: str = "human", reason: str = "") -> bool:
        """批准检查点（CLI / Web API 调用）"""
        return self._decide(checkpoint_id, ApprovalResult.APPROVED, approver, reason)

    def reject(self, checkpoint_id: str, approver: str = "human", reason: str = "") -> bool:
        """拒绝检查点"""
        return self._decide(checkpoint_id, ApprovalResult.REJECTED, approver, reason)

    def _decide(self, checkpoint_id: str, result: ApprovalResult,
                 approver: str, reason: str) -> bool:
        with self._lock:
            if checkpoint_id not in self._pending:
                return False
            if checkpoint_id in self._decisions:
                return False  # 已有决策

            pending_chk = self._pending[checkpoint_id]
            latency_ms = (
                datetime.now() - datetime.fromisoformat(pending_chk.created_at)
            ).total_seconds() * 1000

            decision = ApprovalRecord(
                checkpoint_id=checkpoint_id,
                result=result,
                approver=approver,
                reason=reason,
                latency_ms=latency_ms,
            )

            self._decisions[checkpoint_id] = decision
            HITL_POLICY.notify(decision)

        # 移动文件
        self._move_to_result(checkpoint_id, result)

        # 触发等待线程
        evt = self._events.get(checkpoint_id)
        if evt:
            evt.set()

        return True

    def _move_to_result(self, checkpoint_id: str, result: ApprovalResult):
        src = os.path.join(PENDING_DIR, f"{checkpoint_id}.json")
        if not os.path.exists(src):
            return

        if result == ApprovalResult.APPROVED:
            dest = os.path.join(APPROVED_DIR, f"{checkpoint_id}.json")
        else:
            dest = os.path.join(REJECTED_DIR, f"{checkpoint_id}.json")

        os.rename(src, dest)

    def _notify_approvers(self, checkpoint: Checkpoint):
        """通知审批者（可扩展：Webhook / OpenClaw消息 / WebSocket）"""
        # 默认只打印日志
        print(f"[HITL] ⏸  Checkpoint {checkpoint.id} awaiting approval:")
        print(f"       Task: {checkpoint.task_id}")
        print(f"       Type: {checkpoint.type.value}")
        print(f"       Desc: {checkpoint.description}")
        print(f"       Approve: python checkpoint.py approve {checkpoint.id}")
        print(f"       Reject:  python checkpoint.py reject  {checkpoint.id}")

        # 尝试通过 OpenClaw 通知
        self._notify_via_openclaw(checkpoint)

        # 尝试 webhook
        self._notify_via_webhook(checkpoint)

    def _notify_via_openclaw(self, checkpoint: Checkpoint):
        """通过 OpenClaw nodes.notify 通知"""
        try:
            from nodes import notify
            notify(
                title=f"⏸ Approve Checkpoint: {checkpoint.task_id[:20]}",
                body=checkpoint.description[:200],
                priority="timeSensitive",
            )
        except Exception:
            pass

    def _notify_via_webhook(self, checkpoint: Checkpoint):
        """通过 webhook 通知"""
        webhook_url = os.environ.get("CLAWSWARM_HITL_WEBHOOK")
        if not webhook_url:
            return
        try:
            import requests
            requests.post(webhook_url, json={
                "event": "checkpoint_pending",
                "checkpoint": checkpoint.to_dict(),
                "action": f"python checkpoint.py approve {checkpoint.id}",
            }, timeout=5)
        except Exception:
            pass

    # ── 管理 API ──────────────────────────────────────────────────────

    def list_pending(self) -> List[Checkpoint]:
        with self._lock:
            return list(self._pending.values())

    def get_decision(self, checkpoint_id: str) -> Optional[ApprovalRecord]:
        with self._lock:
            return self._decisions.get(checkpoint_id)

    def stats(self) -> dict:
        with self._lock:
            return {
                "pending":  len(self._pending),
                "decided":   len(self._decisions),
                "approved":  sum(1 for d in self._decisions.values() if d.result == ApprovalResult.APPROVED),
                "rejected":  sum(1 for d in self._decisions.values() if d.result == ApprovalResult.REJECTED),
                "timeout":   sum(1 for d in self._decisions.values() if d.result == ApprovalResult.TIMEOUT),
                "policy":    HITL_POLICY._mode,
            }


# 全局单例
_global_manager: Optional[CheckpointManager] = None

def get_manager() -> CheckpointManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = CheckpointManager()
    return _global_manager


# ── 便捷函数 ──────────────────────────────────────────────────────────────

def checkpoint(
    task_id: str,
    description: str,
    type: CheckpointType = CheckpointType.APPROVAL,
    timeout: float = 300.0,
    metadata: Dict = None,
) -> ApprovalRecord:
    """
    一句话触发检查点。

    用法:
        result = checkpoint("t_001", "确认删除生产数据库？", type=CheckpointType.CONFIRM)
        if result.result == ApprovalResult.APPROVED:
            delete_production_db()
    """
    mgr = get_manager()
    chk = mgr.create(task_id, type, description, metadata)
    return mgr.wait(chk.id, timeout=timeout)


# ── CLI 入口 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ClawSwarm HITL Checkpoint Manager")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="列出待审批检查点")
    p = sub.add_parser("stats", help="显示检查点统计")
    p = sub.add_parser("approve", help="批准检查点")
    p.add_argument("checkpoint_id")
    p.add_argument("--reason", "-r", default="")
    p.add_argument("--approver", default="cli")

    p = sub.add_parser("reject", help="拒绝检查点")
    p.add_argument("checkpoint_id")
    p.add_argument("--reason", "-r", default="")
    p.add_argument("--approver", default="cli")

    p = sub.add_parser("set-policy", help="设置审批策略")
    p.add_argument("mode", choices=["always_approve", "always_require", "by_priority"])
    p.add_argument("--threshold", type=int, default=5)

    p = sub.add_parser("test", help="测试检查点（创建+等待）")
    p.add_argument("--timeout", type=float, default=10)

    args = parser.parse_args(sys.argv[1:])
    mgr = get_manager()

    if args.cmd == "list":
        pending = mgr.list_pending()
        if not pending:
            print("No pending checkpoints.")
        for chk in pending:
            print(f"  {chk.id}  [{chk.type.value}]  {chk.description}")

    elif args.cmd == "stats":
        s = mgr.stats()
        print(f"Policy: {s['policy']}")
        print(f"Pending: {s['pending']}  Approved: {s['approved']}  Rejected: {s['rejected']}  Timeout: {s['timeout']}")

    elif args.cmd == "approve":
        ok = mgr.approve(args.checkpoint_id, args.approver, args.reason)
        print(f"{'Approved' if ok else 'Failed'}: {args.checkpoint_id}")

    elif args.cmd == "reject":
        ok = mgr.reject(args.checkpoint_id, args.approver, args.reason)
        print(f"{'Rejected' if ok else 'Failed'}: {args.checkpoint_id}")

    elif args.cmd == "set-policy":
        if args.mode == "always_approve":
            HITL_POLICY.set_always_approve()
        elif args.mode == "always_require":
            HITL_POLICY.set_always_require()
        elif args.mode == "by_priority":
            HITL_POLICY.set_require_above_priority(args.threshold)
        print(f"Policy set to: {args.mode}")

    elif args.cmd == "test":
        print(f"Creating test checkpoint (timeout={args.timeout}s)...")
        result = checkpoint(
            task_id="test_task",
            description="测试审批：确认执行测试任务？",
            type=CheckpointType.CONFIRM,
            timeout=args.timeout,
            metadata={"task_type": "test"},
        )
        print(f"Result: {result.result.value}")
        print(f"Approver: {result.approver}")
        print(f"Reason: {result.reason}")

    else:
        parser.print_help()
