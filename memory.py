"""
ClawSwarm - Agent 记忆系统

借鉴 LangGraph/CrewAI 的记忆设计：
- 短期记忆：当前会话内的对话历史（ring buffer）
- 长期记忆：持久化到文件，支持向量搜索（BM25）
- 工作记忆：当前任务上下文（TaskContext）

核心类:
    ShortTermMemory  — 对话历史（窗口限制）
    LongTermMemory  — 持久化记忆（跨会话）
    WorkingMemory   — 当前任务的工作上下文
    MemoryStore     — 统一记忆接口
"""

import os, json, time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any
from collections import deque
from threading import RLock

from paths import BASE_DIR

# ── 记忆条目 ──────────────────────────────────────────────────────────────

@dataclass
class MemoryItem:
    """记忆条目"""
    id:        str
    role:      str           # "user" / "assistant" / "system" / "observation"
    content:   str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata:  Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "role":      self.role,
            "content":   self.content,
            "timestamp": self.timestamp,
            "metadata":  self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryItem":
        return cls(**data)


# ── 短期记忆 ──────────────────────────────────────────────────────────────

class ShortTermMemory:
    """
    对话历史记忆（ring buffer）。

    特点：
    - 固定窗口大小（max_items），超出自动丢弃最旧的
    - 支持 summarization（自动摘要长对话）
    - 线程安全
    """

    def __init__(self, max_items: int = 100, max_chars: int = 50000):
        self.max_items = max_items
        self.max_chars = max_chars
        self._items: deque = deque(maxlen=max_items)
        self._lock = RLock()
        self._summary: Optional[str] = None

    def add(self, role: str, content: str, metadata: Dict = None) -> str:
        """添加记忆条目"""
        item_id = f"mem_{int(time.time() * 1000)}"
        item = MemoryItem(id=item_id, role=role, content=content, metadata=metadata or {})
        with self._lock:
            self._items.append(item)
            # 超过字符限制，生成摘要
            total_chars = sum(len(i.content) for i in self._items)
            if total_chars > self.max_chars:
                self._summarize()
        return item_id

    def add_message(self, role: str, content: str) -> str:
        """添加对话消息（快捷方法）"""
        return self.add(role, content, {"type": "message"})

    def _summarize(self):
        """生成摘要以压缩记忆"""
        if self._summary:
            # 已有摘要，只保留摘要 + 最近 N 条
            summary_item = MemoryItem(
                id="__summary__",
                role="system",
                content=f"[历史摘要] {self._summary}",
                metadata={"type": "summary"},
            )
            # 保留最近的一半
            keep = list(self._items)[-self.max_items // 2:]
            self._items = deque([summary_item] + keep, maxlen=self.max_items)
        else:
            # 首次摘要：只保留最近的一半
            keep = list(self._items)[-self.max_items // 2:]
            self._items = deque(keep, maxlen=self.max_items)

    def get_recent(self, n: int = 20) -> List[MemoryItem]:
        """获取最近 N 条记忆"""
        with self._lock:
            return list(self._items)[-n:]

    def get_all(self) -> List[MemoryItem]:
        """获取全部记忆"""
        with self._lock:
            return list(self._items)

    def get_context(self, n: int = 10) -> str:
        """
        获取记忆上下文（供 LLM 使用）。
        格式化为对话字符串。
        """
        items = self.get_recent(n)
        lines = []
        for item in items:
            if item.id == "__summary__":
                lines.append(f"[摘要] {item.content}")
            else:
                role_label = {"user": "User", "assistant": "Assistant",
                              "system": "System", "observation": "观察"}.get(item.role, item.role)
                lines.append(f"{role_label}: {item.content[:500]}")
        return "\n".join(lines)

    def set_summary(self, summary: str):
        """手动设置摘要"""
        with self._lock:
            self._summary = summary

    def clear(self):
        """清空记忆"""
        with self._lock:
            self._items.clear()
            self._summary = None

    def __len__(self) -> int:
        return len(self._items)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "items":   [i.to_dict() for i in self._items],
                "summary": self._summary,
            }


# ── 长期记忆 ──────────────────────────────────────────────────────────────

class LongTermMemory:
    """
    持久化记忆（跨会话）。

    存储在 files/ 目录，每个 agent 一个子目录，
    按日期组织记忆文件。

    特点：
    - 自动持久化（每 N 条写入磁盘）
    - BM25 关键词搜索
    - 时间范围过滤
    """

    def __init__(self, agent_id: str, base_dir: str = None):
        self.agent_id = agent_id
        self.base_dir = base_dir or os.path.join(BASE_DIR, "memory", agent_id)
        self._items: Dict[str, MemoryItem] = {}
        self._dirty = False
        self._load()

    def _memory_file(self, date: str = None) -> str:
        date = date or datetime.now().strftime("%Y-%m-%d")
        d = os.path.join(self.base_dir, date)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "memory.jsonl")

    def _load(self):
        """加载最近 7 天的记忆"""
        today = datetime.now()
        for i in range(7):
            ts = today.timestamp() - i * 86400
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            filepath = self._memory_file(date_str)
            if not os.path.exists(filepath):
                continue
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = MemoryItem.from_dict(json.loads(line))
                        self._items[item.id] = item
                    except Exception:
                        pass

    def _persist(self, item: MemoryItem):
        """持久化单条记忆"""
        date_str = item.timestamp[:10]
        filepath = self._memory_file(date_str)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    def add(self, role: str, content: str, metadata: Dict = None) -> str:
        """添加记忆并持久化"""
        item_id = f"ltm_{self.agent_id}_{int(time.time() * 1000)}"
        item = MemoryItem(id=item_id, role=role, content=content, metadata=metadata or {})
        self._items[item_id] = item
        self._persist(item)
        self._dirty = True
        return item_id

    def search(self, query: str, top_k: int = 5, days: int = 7) -> List[MemoryItem]:
        """
        关键词搜索（BM25 简化版）。

        策略：
        1. query 分词
        2. 对每条记忆，计算 query 词在内容中的出现次数
        3. 排序返回
        """
        query_words = set(query.lower().split())
        cutoff = datetime.now().timestamp() - days * 86400
        scored = []
        for item in self._items.values():
            if datetime.fromisoformat(item.timestamp).timestamp() < cutoff:
                continue
            content_lower = item.content.lower()
            score = sum(1 for w in query_words if w in content_lower)
            # 额外奖励：完全匹配 query
            if query.lower() in content_lower:
                score += 10
            if score > 0:
                scored.append((score, -len(scored), item))
        scored.sort(reverse=True)
        return [item for _, _, item in scored[:top_k]]

    def get_recent(self, n: int = 20, days: int = 7) -> List[MemoryItem]:
        """获取最近 N 条记忆"""
        cutoff = datetime.now().timestamp() - days * 86400
        recent = [
            (datetime.fromisoformat(item.timestamp).timestamp(), item)
            for item in self._items.values()
            if datetime.fromisoformat(item.timestamp).timestamp() >= cutoff
        ]
        recent.sort(reverse=True)
        return [item for _, item in recent[:n]]

    def get_context(self, query: str = None, top_k: int = 5) -> str:
        """获取相关记忆上下文"""
        if query:
            items = self.search(query, top_k=top_k)
        else:
            items = self.get_recent(n=top_k)
        if not items:
            return "(无相关长期记忆)"
        parts = []
        for item in items:
            ts = item.timestamp[:16]
            parts.append(f"[{ts}][{item.role}] {item.content[:300]}")
        return "\n".join(parts)


# ── 工作记忆（当前任务上下文）────────────────────────

@dataclass
class TaskContext:
    """当前任务的执行上下文"""
    task_id:    str
    description: str
    goal:        str           # 最终目标
    plan:        List[str] = field(default_factory=list)   # 执行计划
    artifacts:   Dict[str, Any] = field(default_factory=dict)  # 中间产物
    status:      str = "running"
    started_at:  str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str = None

    def add_artifact(self, key: str, value: Any):
        """添加中间产物"""
        self.artifacts[key] = {"value": value, "ts": datetime.now().isoformat()}

    def to_dict(self) -> dict:
        return {
            "task_id":     self.task_id,
            "description": self.description,
            "goal":        self.goal,
            "plan":        self.plan,
            "artifacts":   self.artifacts,
            "status":      self.status,
            "started_at":  self.started_at,
            "completed_at": self.completed_at,
        }


class WorkingMemory:
    """
    工作记忆：当前任务的状态和中间产物。

    每个 Agent 实例有一个 WorkingMemory，
    记录当前任务的执行状态和所有中间结果。
    """

    def __init__(self):
        self._contexts: Dict[str, TaskContext] = {}
        self._current: Optional[str] = None
        self._lock = RLock()

    def start_task(self, task_id: str, description: str, goal: str = None) -> TaskContext:
        """开始新任务"""
        ctx = TaskContext(task_id=task_id, description=description, goal=goal or description)
        with self._lock:
            self._contexts[task_id] = ctx
            self._current = task_id
        return ctx

    def get_current(self) -> Optional[TaskContext]:
        """获取当前任务上下文"""
        with self._lock:
            if self._current and self._current in self._contexts:
                return self._contexts[self._current]
        return None

    def get(self, task_id: str) -> Optional[TaskContext]:
        return self._contexts.get(task_id)

    def complete_task(self, task_id: str):
        """标记任务完成"""
        with self._lock:
            if task_id in self._contexts:
                self._contexts[task_id].status = "done"
                self._contexts[task_id].completed_at = datetime.now().isoformat()
                if self._current == task_id:
                    self._current = None

    def update_plan(self, task_id: str, plan: List[str]):
        """更新执行计划"""
        if task_id in self._contexts:
            self._contexts[task_id].plan = plan

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "current":   self._current,
                "contexts":  {k: v.to_dict() for k, v in self._contexts.items()},
            }


# ── 统一记忆接口 ──────────────────────────────────────────────────────────

class MemoryStore:
    """
    统一记忆接口：封装短/长/工作记忆。

    用法:
        store = MemoryStore("claw_gamma")
        store.short.add_message("user", "分析这份报告")
        store.long.add("observation", "关键数据：增长 30%")
        ctx = store.working.start_task("t_001", "分析报告")
        # 获取完整上下文给 LLM
        context = store.get_full_context(n_recent=10)
    """

    def __init__(self, agent_id: str, short_max: int = 50):
        self.agent_id = agent_id
        self.short = ShortTermMemory(max_items=short_max)
        self.long  = LongTermMemory(agent_id=agent_id)
        self.working = WorkingMemory()

    def add_message(self, role: str, content: str):
        """添加对话消息（同时记录到短期+长期）"""
        self.short.add_message(role, content)
        self.long.add(role, content)

    def get_full_context(self, n_recent: int = 10) -> str:
        """
        获取完整上下文供 LLM 使用。
        格式：工作目标 + 短期历史 + 相关长期记忆
        """
        ctx = self.working.get_current()
        parts = []

        if ctx:
            parts.append(f"【当前任务】{ctx.description}")
            if ctx.goal:
                parts.append(f"【目标】{ctx.goal}")
            if ctx.plan:
                parts.append(f"【计划】{' → '.join(ctx.plan)}")
            if ctx.artifacts:
                parts.append("【已产出】")
                for k, v in ctx.artifacts.items():
                    val = v.get("value", v) if isinstance(v, dict) else v
                    parts.append(f"  - {k}: {str(val)[:200]}")

        recent = self.short.get_context(n=n_recent)
        if recent:
            parts.append(f"\n【最近对话】\n{recent}")

        return "\n".join(parts) if parts else ""

    def get_context_for_llm(self) -> str:
        """供 LLM 使用的记忆上下文"""
        return self.get_full_context(n_recent=20)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "short":    self.short.to_dict(),
            "working":  self.working.to_dict(),
        }


# ── 全局 Agent 记忆 ───────────────────────────────────────────────────────

_agent_memories: Dict[str, MemoryStore] = {}

def get_agent_memory(agent_id: str) -> MemoryStore:
    """获取 Agent 的记忆实例（单例）"""
    if agent_id not in _agent_memories:
        _agent_memories[agent_id] = MemoryStore(agent_id)
    return _agent_memories[agent_id]


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="ClawSwarm Memory")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list", help="列出所有 Agent 记忆")
    sub.add_parser("stats", help="显示记忆统计")

    args = parser.parse_args(sys.argv[1:])

    if args.cmd == "list":
        for aid, mem in _agent_memories.items():
            print(f"{aid}: short={len(mem.short)} long={len(mem.long._items)}")

    elif args.cmd == "stats":
        print("Agent 记忆统计:")
        for aid in os.listdir(os.path.join(BASE_DIR, "memory")):
            mem_dir = os.path.join(BASE_DIR, "memory", aid)
            files = [f for f in os.listdir(mem_dir) if f.endswith(".jsonl")]
            print(f"  {aid}: {len(files)} days of memory")

    else:
        print("ClawSwarm Memory CLI")
        print("  python memory.py list   # 列出记忆")
        print("  python memory.py stats  # 显示统计")
