"""
ClawSwarm Orchestrator - 任务编排器

负责：
1. 接收高层任务描述
2. 智能分解为子任务（规则引擎）
3. 构建 DAG 依赖图
4. 并行调度 + 串行协调
5. 实时收集结果
6. 聚合输出

核心流程：
  用户: "搜索 Python 最新资讯并写一份报告"
         ↓
  Orchestrator.decompose()  → 拆成 [fetch, report] 两个子任务
         ↓
  Scheduler.create_task()    → 写入 queue/，自动匹配节点
         ↓
  节点并行执行
         ↓
  Aggregator.aggregate()      → 收集结果，合成最终输出
         ↓
  用户: 收到结构化结果
"""

import os
import re
import time
import json
import uuid
import asyncio
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict

from paths import QUEUE_DIR, RESULTS_DIR, AGENTS_DIR, ensure_dirs, can_node_handle, find_best_node
from swarm_scheduler import create_task, get_online_nodes

try:
    from watchdog.observers import Observer
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


# ── 任务分类器 ─────────────────────────────────────────────────────────────

TASK_KEYWORDS: Dict[str, List[str]] = {
    "fetch":   ["搜索", "查询", "查找", "抓取", "获取", "爬取", "fetch", "search", "scrape", "crawl", "get", "url", "网址", "网页"],
    "analyze": ["分析", "评估", "对比", "统计", "analyze", "compare", "evaluate", "stats"],
    "report":  ["写", "生成", "撰写", "报告", "摘要", "总结", "整理", "write", "report", "summarize", "draft"],
    "code":    ["代码", "编程", "实现", "开发", "编写", "code", "implement", "develop", "program", "函数", "class"],
    "read":    ["读", "读取", "打开", "查看", "检查", "read", "open", "view", "check"],
}

# 连接词：分割子任务的边界
SPLITTERS = re.compile(r'[，,；;]|然后|接着|之后|并|同时|另外|以及|还有')


def classify_task(text: str) -> str:
    """根据关键词对任务描述进行分类"""
    scores: Dict[str, int] = defaultdict(int)
    for task_type, keywords in TASK_KEYWORDS.items():
        for kw in keywords:
            if re.search(re.escape(kw), text, re.IGNORECASE):
                scores[task_type] += 1
    return max(scores, key=scores.get) if scores else "general"


# ── 子任务模型 ─────────────────────────────────────────────────────────────

@dataclass
class SubTask:
    id: str
    type: str
    description: str
    depends_on: List[str] = field(default_factory=list)
    swarm_task_id: Optional[str] = None
    status: str = "pending"
    result: Any = None


# ── 任务分解器 ─────────────────────────────────────────────────────────────

class TaskDecomposer:
    """
    将高层自然语言任务拆解为子任务 DAG。
    
    分解策略：
    - 先按连接词拆分
    - 无法拆分 → 单一任务
    - 多个子任务 → 按类型自动注入依赖
      (report/analyze 依赖前面的 fetch)
    """

    def decompose(self, description: str) -> List[SubTask]:
        """分解高层描述，返回子任务列表（无依赖顺序）"""
        # 按连接词分割
        segments = [s.strip() for s in SPLITTERS.split(description) if s.strip()]

        if len(segments) == 1:
            # 单一任务
            return [SubTask(
                id="sub_0",
                type=classify_task(description),
                description=description,
            )]

        sub_tasks = []
        for i, seg in enumerate(segments):
            sub_tasks.append(SubTask(
                id=f"sub_{i}",
                type=classify_task(seg),
                description=seg,
            ))

        # 依赖注入：report/analyze 自动依赖前一个 fetch
        for i, st in enumerate(sub_tasks):
            if st.type in ("report", "analyze"):
                for j in range(i):
                    if sub_tasks[j].type == "fetch":
                        st.depends_on.append(sub_tasks[j].id)

        return sub_tasks


# ── 结果聚合器 ─────────────────────────────────────────────────────────────

class ResultAggregator:
    """
    收集子任务结果，聚合为最终输出。
    支持并行收集 + 智能格式化。
    """

    SECTION_EMOJI = {
        "fetch":   "📡",
        "analyze": "🔍",
        "report":  "📝",
        "code":    "💻",
        "read":    "📖",
        "general": "📦",
    }

    def aggregate(self, sub_tasks: List[SubTask]) -> str:
        """将所有子任务结果聚合成最终报告"""
        parts = []
        for st in sub_tasks:
            emoji = self.SECTION_EMOJI.get(st.type, "📦")
            parts.append(f"\n{emoji} **{st.description[:60]}**\n")
            parts.append(self._format_result(st))
        return "\n".join(parts) if parts else "（无结果）"

    def _format_result(self, st: SubTask) -> str:
        """提取并格式化单个子任务的结果"""
        if st.status != "done" or st.result is None:
            return f"   ⏳ {st.status}"

        r = st.result
        content = ""

        if isinstance(r, str):
            content = r
        elif isinstance(r, dict):
            # 优先字段：output > result > content > stdout > text
            for key in ["output", "result", "content", "stdout", "text"]:
                if key in r and r[key]:
                    val = r[key]
                    content = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
                    break
            if not content:
                content = json.dumps(r, ensure_ascii=False, indent=2)
        else:
            content = str(r)

        # 截断
        if len(content) > 3000:
            content = content[:3000] + "\n... _(已截断)_"
        elif not content.strip():
            content = "(空结果)"

        return "   " + content.replace("\n", "\n   ")


# ── Watchdog 实时结果收集器 ────────────────────────────────────────────────

class ResultWatcher:
    """
    使用 watchdog 监听 results/ 目录，新结果文件出现立刻通知。
    比轮询更实时，比 blocking read 更可控。
    """

    def __init__(self):
        self._results: Dict[str, dict] = {}
        self._found = threading.Event()
        self._done = threading.Event()
        self._observer = None

    def start(self):
        if not HAS_WATCHDOG:
            return
        try:
            from watchdog.events import FileSystemEventHandler

            class RHandler(FileSystemEventHandler):
                def __init__(wself, watcher):
                    wself.watcher = watcher

                def on_created(wself, event):
                    if not event.is_directory and event.src_path.endswith(".json") and os.path.basename(event.src_path).startswith("r_"):
                        try:
                            with open(event.src_path, encoding="utf-8") as f:
                                data = json.load(f)
                            tid = data.get("task_id", "")
                            wself.watcher._results[tid] = data
                            wself.watcher._found.set()
                        except Exception:
                            pass

            handler = RHandler(self)
            self._observer = Observer()
            self._observer.schedule(handler, RESULTS_DIR, recursive=False)
            self._observer.daemon = True
            self._observer.start()
        except Exception:
            pass  # watchdog 不可用，fallback 到轮询

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)

    def wait_for(self, task_ids: List[str], timeout: float) -> Dict[str, dict]:
        """等待指定任务ID的结果，超时返回已收集到的"""
        deadline = time.time() + timeout
        pending = set(task_ids)

        while pending and time.time() < deadline:
            # 有 watchdog 时用事件等待，否则轮询
            if self._found.is_set():
                self._found.clear()
                # 再次检查 pending
                still_pending = set()
                for tid in pending:
                    if tid in self._results:
                        pass  # 已收集
                    elif os.path.exists(os.path.join(RESULTS_DIR, f"r_{tid}.json")):
                        try:
                            with open(os.path.join(RESULTS_DIR, f"r_{tid}.json"), encoding="utf-8") as f:
                                self._results[tid] = json.load(f)
                        except Exception:
                            still_pending.add(tid)
                    else:
                        still_pending.add(tid)
                pending = still_pending
            else:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._found.wait(timeout=min(remaining, 0.5))

        # 最后一次同步扫描
        for tid in pending:
            if tid not in self._results:
                rf = os.path.join(RESULTS_DIR, f"r_{tid}.json")
                if os.path.exists(rf):
                    try:
                        with open(rf, encoding="utf-8") as f:
                            self._results[tid] = json.load(f)
                    except Exception:
                        pass

        return {tid: self._results[tid] for tid in task_ids if tid in self._results}


# ── 编排器（核心）──────────────────────────────────────────────────────────

@dataclass
class OrchestratorResult:
    """编排执行结果"""
    description: str
    sub_tasks: List[SubTask]
    final_output: str
    total_duration: float
    success: bool
    errors: List[str] = field(default_factory=list)


class Orchestrator:
    """
    ClawSwarm 任务编排器
    
    用法:
        orc = Orchestrator(timeout=120)
        result = orc.run("搜索今天深圳天气并写一份简短报告")
        print(result.final_output)
    
    也支持流式输出（通过 on_progress 回调）：
        orc.run("分析这个", on_progress=print)
    """

    def __init__(self, timeout: float = 120.0, poll_interval: float = 0.5):
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.decomposer = TaskDecomposer()
        self.aggregator = ResultAggregator()

    # ── 公开 API ─────────────────────────────────────────────────────────

    def run(self, description: str, on_progress=None) -> OrchestratorResult:
        """
        端到端执行一个高层任务。

        Args:
            description: 自然语言任务描述
            on_progress: 可选回调，每完成一个子任务调用 `callback(sub_task)`

        Returns:
            OrchestratorResult: 包含所有子任务和最终聚合结果
        """
        ensure_dirs()
        start_time = time.time()
        errors: List[str] = []

        print(f"\n🦞 ClawSwarm Orchestrator")
        print(f"📋 输入: {description}")

        # 1. 分解
        sub_tasks = self.decomposer.decompose(description)
        print(f"\n📊 分解 ({len(sub_tasks)} 个子任务):")
        for st in sub_tasks:
            deps = f" ← [{', '.join(st.depends_on)}]" if st.depends_on else ""
            print(f"   [{st.id}] {st.type:8s}{deps}  {st.description[:50]}")

        if len(sub_tasks) == 1:
            result = self._run_single(sub_tasks[0], on_progress)
            result.total_duration = time.time() - start_time
            return result

        # 2. 调度：分层执行（DAG 拓扑序）
        #    先执行所有无依赖的（并行），再执行有依赖的（等待完成后串行）
        scheduled = set()
        in_flight: Dict[str, asyncio.Future] = {}

        def mark_done(st_id):
            scheduled.add(st_id)
            if on_progress and st_id in in_flight:
                for st in sub_tasks:
                    if st.id == st_id:
                        on_progress(st)
                        break

        # 并行执行无依赖的子任务
        for st in sub_tasks:
            if not st.depends_on:
                tid, swarm_task = self._schedule(st)
                st.swarm_task_id = tid
                in_flight[st.id] = tid

        # 等待所有并行任务完成
        pending_ids = [st.swarm_task_id for st in sub_tasks if st.swarm_task_id]

        watcher = ResultWatcher()
        watcher.start()
        try:
            results = watcher.wait_for(pending_ids, timeout=self.timeout)
        finally:
            watcher.stop()

        # 填充结果
        for st in sub_tasks:
            if st.swarm_task_id and st.swarm_task_id in results:
                r = results[st.swarm_task_id]
                st.status = r.get("status", "done")
                st.result = r.get("result")
                if st.status == "failed":
                    errors.append(f"{st.id}: {r.get('error', 'unknown')}")

        # 串行执行有依赖的（每完成一个通知一次）
        for st in sub_tasks:
            if st.depends_on:
                # 检查依赖是否都已完成
                deps_done = all(scheduled.intersection([d] + [d for d in {st.depends_on} if d in scheduled]))
                # 简化为：所有并行任务的结果已收集，再执行串行
                if st.id not in scheduled:
                    tid, swarm_task = self._schedule(st)
                    st.swarm_task_id = tid
                    # 等待这一个
                    r = watcher.wait_for([tid], timeout=self.timeout)
                    if tid in r:
                        st.status = r[tid].get("status", "done")
                        st.result = r[tid].get("result")
                        if st.status == "failed":
                            errors.append(f"{st.id}: {r[tid].get('error', 'unknown')}")
                    mark_done(st.id)

        # 3. 聚合
        final_output = self.aggregator.aggregate(sub_tasks)

        duration = time.time() - start_time
        print(f"\n✅ 完成 ({duration:.1f}s, {len(sub_tasks)} 子任务)")
        if errors:
            for e in errors:
                print(f"   ⚠️  {e}")

        return OrchestratorResult(
            description=description,
            sub_tasks=sub_tasks,
            final_output=final_output,
            total_duration=duration,
            success=len(errors) == 0,
            errors=errors,
        )

    def _run_single(self, st: SubTask, on_progress) -> OrchestratorResult:
        """运行单个子任务"""
        start = time.time()
        tid, swarm_task = self._schedule(st)
        st.swarm_task_id = tid

        print(f"\n⏳ 执行: {st.description[:60]}")

        watcher = ResultWatcher()
        watcher.start()
        try:
            results = watcher.wait_for([tid], timeout=self.timeout)
        finally:
            watcher.stop()

        if tid in results:
            st.status = results[tid].get("status", "done")
            st.result = results[tid].get("result")
        else:
            st.status = "timeout"
            st.result = None

        if on_progress:
            on_progress(st)

        return OrchestratorResult(
            description=st.description,
            sub_tasks=[st],
            final_output=self.aggregator.aggregate([st]),
            total_duration=time.time() - start,
            success=st.status == "done",
            errors=[] if st.status == "done" else [f"{st.id}: {st.status}"],
        )

    def _schedule(self, st: SubTask) -> tuple:
        """调度单个子任务到 swarm"""
        tid, task = create_task(
            st.description,
            task_type=st.type,
            metadata={"sub_task_id": st.id},
        )
        node = task.get("assigned_to", "any")
        print(f"   → {tid}  [{st.type}]  →  {node or 'unassigned'}")
        return tid, task


# ── 便捷函数 ──────────────────────────────────────────────────────────────

def run(description: str, timeout: float = 120.0) -> str:
    """
    一句话执行高层任务，返回聚合结果文本。
    
    用法:
        result = run("搜索 Python 最新资讯并写一份报告")
        print(result)
    """
    orc = Orchestrator(timeout=timeout)
    r = orc.run(description)
    return r.final_output


# ── CLI 入口 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    desc = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""

    if not desc:
        print("用法: python orchestrator.py <任务描述>")
        print("示例: python orchestrator.py 搜索今天深圳天气并写一份简短报告")
        sys.exit(1)

    print("=" * 60)
    result = run(desc)
    print("=" * 60)
    print(result)
