"""
ClawSwarm Orchestrator - 任务编排器

负责：
1. 接收高层任务描述
2. LLM 智能分解为子任务 DAG
3. 并行调度 + 串行协调
4. 实时收集结果
5. LLM 聚合输出

核心流程：
  用户: "搜索 Python 最新资讯并写一份报告"
         ↓
  Orchestrator.decompose()  → LLM 拆成 [fetch, report] 两个子任务
         ↓
  Scheduler.create_task()    → 写入 queue/，自动匹配节点
         ↓
  节点并行执行
         ↓
  Aggregator.aggregate()      → LLM 合成最终报告
         ↓
  用户: 收到结构化结果
"""

import os, re, time, json, uuid, asyncio, threading, sys
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except:
    pass


from paths import QUEUE_DIR, RESULTS_DIR, AGENTS_DIR, ensure_dirs, can_node_handle, find_best_node

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except:
    pass
from swarm_scheduler import create_task, get_online_nodes

# LLM 支持（可选，无 API Key 时降级到规则引擎）
try:
    from llm import chat, Message, create_llm_client
    HAS_LLM = True
except ImportError:
    HAS_LLM = False


# ── 任务分类器 ─────────────────────────────────────────────────────────────

# 关键词按长度分档：短词(1-2)权重1，中词(3-4)权重2，长词(5+)权重3
# 核心策略：
# - 中文关键词（首个字符为CJK）：自由子串匹配，不限边界
# - 英文关键词：严格词边界匹配（避免 "write" 抢夺 "write code" 中 "code" 的优先级）
# - "write" 从 report 列表删除（与 code 列表 "code" 冲突）
# - "代码" 只在 code 列表（从 report 删除，避免与 code 冲突）
TASK_KEYWORDS: Dict[str, List[str]] = {
    "fetch":   ["搜索", "查询", "查找", "抓取", "获取", "爬取", "fetch", "search", "scrape", "crawl", "get", "url", "网址", "网页"],
    "analyze": ["分析", "评估", "对比", "统计", "analyze", "compare", "evaluate", "stats"],
    # "write" 已从 report 列表删除（与 code 列表 "code" 冲突）
    # "report" 保留：与 code 列表无重叠，权重 6
    # 单字中文关键词（"写"/"读"/"查"）在 classify_task 中有 2x 加成
    "report":  ["写", "生成", "撰写", "报告", "摘要", "总结", "整理", "report", "draft", "summarize"],
    "code":    ["代码", "编程", "实现", "函数", "class", "code", "implement", "develop", "program"],
    "read":    ["读", "读取", "打开", "查看", "检查", "read", "open", "view", "check"],
    # shell: 远程节点专有（Kimi Claw），调度器会强制通过 relay 路由
    "shell":   ["执行", "命令", "shell", "bash", "ssh", "远程", "hostname", "uptime",
                "服务器", "server", "linux", "ubuntu", "cmd", "console", "terminal"],
}

SPLITTERS = re.compile(r'[，,；;]|然后|接着|之后|并|同时|另外|以及|还有')



def _is_cjk(ch: str) -> bool:
    return '\u4e00' <= ch <= '\u9fff'

def _kw_hit(text: str, kw: str) -> tuple:
    """
    判断关键词是否命中，返回 (hit: bool, pos: int)。
    - CJK 关键词（首个字符为CJK）：自由子串匹配
    - 英文关键词：要求词边界（空格/标点/字符串边界）
    """
    t = text.lower()
    k = kw.lower()
    idx = t.find(k)
    if idx < 0:
        return (False, -1)
    end_idx = idx + len(k)

    if _is_cjk(k[0]) if k else False:
        # 中文关键词：无边界限制
        return (True, idx)
    else:
        # 英文关键词：要求词边界
        left_ok = idx == 0 or t[idx - 1].isspace() or t[idx - 1] in '，。；？！,.?!;:'
        # 右边界：到达字符串末尾 或 后面是空格/标点
        end_ch = t[end_idx] if end_idx < len(t) else ''
        right_ok = end_idx >= len(t) or end_ch.isspace() or end_ch in '，。；？！,.?!;:'
        return (left_ok or right_ok, idx)


def classify_task(text: str) -> str:
    """
    关键词打分分类，策略：
    1. 词边界匹配（避免 "write" 在 "write code" 中误命中 report）
    2. 按关键词长度降序打分（长词权重高，短词权重低）
    3. 同分时选最长匹配词对应的类别
    """
    type_scores: Dict[str, int] = {}
    type_best_kw: Dict[str, int] = {}
    type_last_pos: Dict[str, int] = {}

    # 按词长降序排列（长词优先匹配）
    all_kws: List[tuple] = []
    for task_type, keywords in TASK_KEYWORDS.items():
        for kw in keywords:
            all_kws.append((kw, task_type, len(kw)))
    all_kws.sort(key=lambda x: -x[2])

    for kw, task_type, klen in all_kws:
        hit, pos = _kw_hit(text, kw)
        if hit:
            # 权重 = 词长
            # 中文单字关键词（1字符CJK）给 2x 加成（"写""读""查" 等独立动词，地位重要）
            is_cjk1 = len(kw) == 1 and _is_cjk(kw[0])
            weight = klen * (2 if is_cjk1 else 1)
            type_scores[task_type] = type_scores.get(task_type, 0) + weight
            type_best_kw[task_type] = max(type_best_kw.get(task_type, 0), klen)
            type_last_pos[task_type] = max(type_last_pos.get(task_type, -1), pos)

    if not type_scores:
        return "general"

    # 同分时：最长匹配词 > 同词长时最后出现者优先
    max_score = max(type_scores.values())
    tied = {t: (type_best_kw[t], type_last_pos[t]) for t in type_scores if type_scores[t] == max_score}
    return max(tied, key=lambda t: (tied[t][0], tied[t][1]))


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
    支持 LLM 智能分解 + 规则引擎 fallback。
    """

    DECOMPOSE_PROMPT = """你是一个任务规划专家。用户会给一个高层任务，你需要将其分解为可执行的子任务。

要求：
1. 每个子任务必须是独立可执行的
2. 明确子任务之间的依赖关系（report/analyze 依赖前面的 research）
3. 标注每个子任务的类型（fetch/analyze/report/code/read/general）
4. 尽量并行化：没有依赖关系的子任务应并行执行
5. 子任务数量控制在 1-5 个

输出格式（JSON array）：
[
  {
    "id": "step_1",
    "type": "fetch",
    "description": "搜索相关信息",
    "depends_on": []
  },
  {
    "id": "step_2", 
    "type": "report",
    "description": "撰写报告",
    "depends_on": ["step_1"]
  }
]

用户任务：{task}

请直接输出 JSON，不要有其他文字。"""

    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm and HAS_LLM

    def decompose(self, description: str) -> List[SubTask]:
        """分解高层描述，返回子任务列表"""
        if self.use_llm:
            try:
                return self._decompose_llm(description)
            except Exception:
                pass  # LLM 失败，降级到规则
        return self._decompose_rule(description)

    def _decompose_llm(self, description: str) -> List[SubTask]:
        """使用 LLM 分解任务"""
        prompt = self.DECOMPOSE_PROMPT.format(task=description)
        resp = chat(
            messages=[Message("user", prompt)],
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=2048,
        )

        if resp.error:
            raise RuntimeError(f"LLM decompose failed: {resp.error}")

        # 解析 JSON
        content = resp.content.strip()
        # 去掉 markdown 代码块
        if content.startswith("```"):
            content = re.sub(r'^```json?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)

        data = json.loads(content)
        sub_tasks = []
        for item in data:
            st = SubTask(
                id=item.get("id", "sub"),
                type=item.get("type", "general"),
                description=item.get("description", ""),
                depends_on=item.get("depends_on", []),
            )
            sub_tasks.append(st)
        return sub_tasks

    def _decompose_rule(self, description: str) -> List[SubTask]:
        """规则引擎分解（fallback）"""
        segments = [s.strip() for s in SPLITTERS.split(description) if s.strip()]

        if len(segments) == 1:
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
                        if sub_tasks[j].id not in st.depends_on:
                            st.depends_on.append(sub_tasks[j].id)

        return sub_tasks


# ── 结果聚合器 ─────────────────────────────────────────────────────────────

class ResultAggregator:
    """
    收集子任务结果，聚合为最终输出。
    支持 LLM 智能聚合 + 模板 fallback。
    """

    AGGREGATE_PROMPT = """你是任务总结专家。以下是多个子任务的执行结果，请将它们聚合成一个完整、结构化的最终报告。

要求：
1. 保留关键信息，去除冗余
2. 按逻辑顺序组织（不要简单拼接）
3. 对比分析时要有洞察
4. 写作用词专业、结构清晰
5. 控制在 2000 字以内

子任务结果：
{results}

请直接输出最终报告，不需要解释。"""

    SECTION_EMOJI = {
        "fetch":   "📡",
        "analyze": "🔍",
        "report":  "📝",
        "code":    "💻",
        "read":    "📖",
        "general": "📦",
    }

    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm and HAS_LLM

    def aggregate(self, sub_tasks: List[SubTask]) -> str:
        """将所有子任务结果聚合成最终报告"""
        # 格式化子任务结果
        results_text = self._format_results(sub_tasks)

        if self.use_llm and len(sub_tasks) > 1:
            try:
                return self._aggregate_llm(results_text)
            except Exception:
                pass  # LLM 失败，降级到模板

        return self._aggregate_template(sub_tasks)

    def _format_results(self, sub_tasks: List[SubTask]) -> str:
        parts = []
        for st in sub_tasks:
            emoji = self.SECTION_EMOJI.get(st.type, "📦")
            parts.append(f"【{st.id}】{st.description}")
            parts.append(f"  状态: {st.status}")
            parts.append(f"  结果: {self._extract_content(st)}")
            parts.append("")
        return "\n".join(parts)

    def _extract_content(self, st: SubTask) -> str:
        """提取单个子任务的结果内容"""
        if st.status != "done" or st.result is None:
            return f"（未完成: {st.status}）"

        r = st.result
        content = ""

        if isinstance(r, str):
            content = r
        elif isinstance(r, dict):
            for key in ["output", "result", "content", "stdout", "text", "content"]:
                if key in r and r[key]:
                    val = r[key]
                    content = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
                    break
            if not content:
                content = json.dumps(r, ensure_ascii=False, indent=2)
        else:
            content = str(r)

        if len(content) > 3000:
            content = content[:3000] + "\n... _(已截断)_"
        elif not content.strip():
            content = "(空结果)"
        return content

    def _aggregate_llm(self, results_text: str) -> str:
        """使用 LLM 聚合"""
        prompt = self.AGGREGATE_PROMPT.format(results=results_text)
        resp = chat(
            messages=[Message("user", prompt)],
            model="gpt-4o-mini",
            temperature=0.5,
            max_tokens=4096,
        )

        if resp.error:
            raise RuntimeError(f"LLM aggregate failed: {resp.error}")

        return resp.content.strip()

    def _aggregate_template(self, sub_tasks: List[SubTask]) -> str:
        """模板聚合（fallback）"""
        parts = []
        for st in sub_tasks:
            emoji = self.SECTION_EMOJI.get(st.type, "📦")
            parts.append(f"\n{emoji} **{st.description[:60]}**\n")
            parts.append("   " + self._extract_content(st).replace("\n", "\n   "))
        return "\n".join(parts) if parts else "（无结果）"


# ── Watchdog 实时结果收集器 ────────────────────────────────────────────────

class ResultWatcher:
    """使用 watchdog 监听 results/ 目录，新结果文件出现立刻通知"""

    def __init__(self):
        self._results: Dict[str, dict] = {}
        self._found = threading.Event()
        self._done = threading.Event()
        self._observer = None

    def start(self):
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            HAS_WATCHDOG = True
        except ImportError:
            HAS_WATCHDOG = False

        if not HAS_WATCHDOG:
            return

        try:
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
            pass

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)

    def wait_for(self, task_ids: List[str], timeout: float) -> Dict[str, dict]:
        """等待指定任务ID的结果，超时返回已收集到的"""
        deadline = time.time() + timeout
        pending = set(task_ids)

        while pending and time.time() < deadline:
            if self._found.is_set():
                self._found.clear()
                still_pending = set()
                for tid in pending:
                    if tid in self._results:
                        pass
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

    def __init__(self, timeout: float = 120.0, use_llm: bool = True):
        self.timeout = timeout
        self.use_llm = use_llm
        self.decomposer = TaskDecomposer(use_llm=use_llm)
        self.aggregator = ResultAggregator(use_llm=use_llm)

    # ── 公开 API ─────────────────────────────────────────────────────────

    def run(self, description: str, on_progress=None) -> OrchestratorResult:
        """
        端到端执行一个高层任务。
        """
        ensure_dirs()
        start_time = time.time()
        errors: List[str] = []

        print(f"\n🦞 ClawSwarm Orchestrator")
        print(f"📋 输入: {description}")
        if self.use_llm and HAS_LLM:
            print(f"🤖 LLM 驱动模式")
        else:
            print(f"📐 规则引擎模式")

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

        # 2. 调度：并行执行所有子任务
        scheduled = set()
        pending_ids: List[str] = []

        for st in sub_tasks:
            if not st.depends_on:
                tid, swarm_task = self._schedule(st)
                st.swarm_task_id = tid
                pending_ids.append(tid)
            else:
                # 有依赖的子任务，依赖完成后才执行
                pass

        # 等待无依赖任务完成
        if pending_ids:
            watcher = ResultWatcher()
            watcher.start()
            try:
                results = watcher.wait_for(pending_ids, timeout=self.timeout)
            finally:
                watcher.stop()

            for tid, r in results.items():
                for st in sub_tasks:
                    if st.swarm_task_id == tid:
                        st.status = r.get("status", "done")
                        st.result = r.get("result")
                        if st.status == "failed":
                            errors.append(f"{st.id}: {r.get('error', 'unknown')}")
                        break
            scheduled.update(pending_ids)

        # 3. 执行有依赖的子任务（串行）
        for st in sub_tasks:
            if st.depends_on:
                tid, swarm_task = self._schedule(st)
                st.swarm_task_id = tid
                watcher = ResultWatcher()
                watcher.start()
                try:
                    r = watcher.wait_for([tid], timeout=self.timeout)
                finally:
                    watcher.stop()
                if tid in r:
                    st.status = r[tid].get("status", "done")
                    st.result = r[tid].get("result")
                    if st.status == "failed":
                        errors.append(f"{st.id}: {r[tid].get('error', 'unknown')}")
                if on_progress:
                    on_progress(st)

        # 4. 聚合
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
        """调度单个子任务到 swarm

        策略：
        - task_type="shell" → 强制路由到远程节点（Kimi Claw）via relay
        - task_type="fetch" → 通过 relay fetch（远程节点有 web 能力）
        - 其他类型 → 通过 create_task（本地调度器自动选择节点）
        """
        # 远程能力类型：强制通过 relay 调度到 Kimi Claw
        REMOTE_TASK_TYPES = {"shell", "fetch"}

        if st.type in REMOTE_TASK_TYPES:
            # 检查是否有在线的远程节点
            try:
                from swarm_scheduler import get_online_nodes, STALE_THRESHOLD_SEC
                from relay_client import RemoteNodeManager
                online = get_online_nodes(STALE_THRESHOLD_SEC)
                remote_nodes = [n for n in online if n.get("is_remote")]

                if remote_nodes:
                    # 使用第一个可用远程节点
                    rn = remote_nodes[0]
                    task_id = f"t_{uuid.uuid4().hex[:12]}"
                    from relay_client import RemoteNode, exec_task_async_via_relay
                    node = RemoteNode(
                        node_id=rn["node_id"],
                        relay_url=rn["relay_url"],
                        name=rn.get("name"),
                        capabilities=rn.get("capabilities"),
                    )
                    # 异步执行，结果写入 results/r_{task_id}.json
                    exec_task_async_via_relay(
                        task_id,
                        st.description,
                        node,
                        timeout=90,
                    )
                    print(f"   → {task_id}  [{st.type}]  →  remote:{rn['node_id']} [via relay]")
                    return task_id, {
                        "id": task_id,
                        "assigned_to": rn["node_id"],
                        "node_type": "remote",
                    }
            except ImportError:
                pass  # relay_client 不可用，降级到本地调度

        # 默认：本地调度器自动选择节点（含远程节点感知）
        # spawn 类型任务 → 通过 spawn_via_agent 处理（agents 能力）
        if st.type in ("spawn", "general", "analyze", "code"):
            try:
                from spawn_manager import spawn_via_agent, wait_for_spawn
                tid, meta = spawn_via_agent(
                    st.description,
                    task_id=f"t_{uuid.uuid4().hex[:12]}",
                    timeout=int(self.timeout),
                    label=f"orch-{st.id}",
                )
                print(f"   → {tid}  [{st.type}]  →  local-spawn [via agent] ⏳")
                # 同步等待 spawn 完成（后台线程处理，轮询结果文件）
                result = wait_for_spawn(tid, timeout=int(self.timeout))
                if result.get("status") == "timeout":
                    print(f"   ⚠️ spawn {tid} 超时，结果可能延迟")
                else:
                    print(f"   ✅ spawn {tid} 完成: {str(result.get('result',''))[:80]}")
                return tid, meta
            except ImportError as e:
                print(f"   ⚠️ spawn_via_agent 不可用: {e}，降级到本地调度")
                pass  # 降级到本地调度

        tid, task = create_task(
            st.description,
            task_type=st.type,
            metadata={"sub_task_id": st.id},
        )
        node = task.get("assigned_to", "any")
        node_type = "remote" if task.get("node_type") == "remote" else ""
        prefix = f"remote:{node}" if node_type == "remote" else (node or "unassigned")
        print(f"   → {tid}  [{st.type}]  →  {prefix}")
        return tid, task


# ── 便捷函数 ──────────────────────────────────────────────────────────────

def run(description: str, timeout: float = 120.0) -> str:
    """
    一句话执行高层任务，返回聚合结果文本。
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
