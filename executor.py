"""
ClawSwarm Executor - 任务执行引擎
负责：任务分发、Agent调用、结果处理、错误重试、超时控制

支持多种执行模式：
- spawn: 调用 OpenClaw sessions_spawn
- fetch: 调用 web_fetch 获取网页
- exec: 调用系统命令
- python: 执行 Python 代码
"""

import json
import os
import sys
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
import traceback

from models import TaskStatus, TaskMode, ExecutionResult
from paths import RESULTS_DIR, QUEUE_DIR
from pathlib import Path as _Path

# ── 数据模型 ─────────────────────────────────────────────────────────────

@dataclass
class ExecutionContext:
    """执行上下文"""
    task_id: str
    node_id: str
    mode: str
    config: dict = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.now)
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 300
    metadata: dict = field(default_factory=dict)

# ── 执行器核心 ─────────────────────────────────────────────────────────────

class TaskExecutor:
    """
    任务执行器
    
    用法:
        executor = TaskExecutor(max_workers=5)
        result = await executor.execute(task_config)
    """
    
    def __init__(
        self,
        max_workers: int = 5,
        default_timeout: int = 300,
        default_retries: int = 3,
        enable_parallel: bool = True
    ):
        self.max_workers = max_workers
        self.default_timeout = default_timeout
        self.default_retries = default_retries
        self.enable_parallel = enable_parallel
        
        # 执行中的任务
        self._running_tasks: Dict[str, ExecutionContext] = {}
        
        # 任务历史
        self._history: List[ExecutionResult] = []
        
        # 回调函数
        self._callbacks: Dict[str, List[Callable]] = {
            "on_start": [],
            "on_success": [],
            "on_failure": [],
            "on_timeout": [],
            "on_retry": [],
        }
        
        # 统计
        self._stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "timeout": 0,
            "retries": 0,
        }
    
    # ── 回调管理 ─────────────────────────────────────────────────────────
    
    def on(self, event: str, callback: Callable):
        """注册回调"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _trigger(self, event: str, *args, **kwargs):
        """触发回调"""
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception:
                pass  # 回调失败不中断
    
    # ── 执行入口 ─────────────────────────────────────────────────────────
    
    async def execute(self, task: dict) -> ExecutionResult:
        """执行单个任务"""
        ctx = ExecutionContext(
            task_id=task.get("id", "unknown"),
            node_id=task.get("node_id", "unknown"),
            mode=task.get("mode", "spawn"),
            config=task.get("config", {}),
            timeout_seconds=task.get("timeout", self.default_timeout),
            max_retries=task.get("retries", self.default_retries),
        )
        
        self._running_tasks[ctx.task_id] = ctx
        self._stats["total"] += 1
        self._trigger("on_start", ctx)
        
        start_time = time.time()
        
        # 重试循环
        while ctx.retry_count <= ctx.max_retries:
            try:
                # 根据模式执行
                result = await self._execute_mode(ctx, task)
                
                duration = time.time() - start_time
                exec_result = ExecutionResult(
                    task_id=ctx.task_id,
                    status="done",
                    output=result,
                    duration_seconds=duration,
                    retries=ctx.retry_count,
                )
                
                self._complete(exec_result)
                return exec_result
                
            except TimeoutError as e:
                ctx.retry_count += 1
                self._stats["retries"] += 1
                self._trigger("on_retry", ctx, e)
                
                if ctx.retry_count > ctx.max_retries:
                    duration = time.time() - start_time
                    exec_result = ExecutionResult(
                        task_id=ctx.task_id,
                        status="timeout",
                        error=str(e),
                        duration_seconds=duration,
                        retries=ctx.retry_count,
                    )
                    self._complete(exec_result)
                    return exec_result
                    
            except Exception as e:
                ctx.retry_count += 1
                self._stats["retries"] += 1
                self._trigger("on_retry", ctx, e)
                
                if ctx.retry_count > ctx.max_retries:
                    duration = time.time() - start_time
                    exec_result = ExecutionResult(
                        task_id=ctx.task_id,
                        status="failed",
                        error=f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
                        duration_seconds=duration,
                        retries=ctx.retry_count,
                    )
                    self._complete(exec_result)
                    return exec_result
        
        # 理论上不会到这里
        return ExecutionResult(
            task_id=ctx.task_id,
            status="failed",
            error="Max retries exceeded",
        )
    
    async def execute_parallel(self, tasks: List[dict]) -> List[ExecutionResult]:
        """并行执行多个任务"""
        if not self.enable_parallel:
            return [await self.execute(t) for t in tasks]
        
        # 使用 asyncio 并行执行
        results = await asyncio.gather(
            *[self.execute(t) for t in tasks],
            return_exceptions=True
        )
        
        # 处理异常
        processed = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                processed.append(ExecutionResult(
                    task_id=tasks[i].get("id", f"task_{i}"),
                    status="failed",
                    error=str(r),
                ))
            else:
                processed.append(r)
        
        return processed
    
    # ── 执行模式 ─────────────────────────────────────────────────────────
    
    async def _execute_mode(self, ctx: ExecutionContext, task: dict) -> Any:
        """根据模式执行"""
        mode = ctx.mode

        if mode == "spawn":
            return await self._execute_spawn(ctx, task)
        elif mode == "fetch":
            return await self._execute_fetch(ctx, task)
        elif mode == "exec":
            return await self._execute_exec(ctx, task)
        elif mode == "python":
            return await self._execute_python(ctx, task)
        elif mode == "workflow":
            return await self._execute_workflow(ctx, task)
        else:
            raise ValueError(f"Unknown execution mode: {mode}")
    
    async def _execute_spawn(self, ctx: ExecutionContext, task: dict) -> Any:
        """
        启动子 Agent（通过 sessions_spawn）

        sessions_spawn 是 OpenClaw 原生的 LLM tool。
        当 executor 在 OpenClaw AI session 内部运行时，
        AI 直接调用 sessions_spawn 即可。

        task 格式:
            {
                "prompt": "Agent 执行指令",
                "result_file": "results/spawn_xxx.json",  // 可选：指定结果文件
                "agent_id": "main",  // 可选：目标 agent
                "model": "gpt-4",    // 可选：指定模型
            }

        返回: {
            "mode": "spawn",
            "session_key": "agent:main:xxx",
            "result_file": "...",   // 结果文件路径
            "status": "spawned",   // 已入队，等待结果
            "executed_at": "...",
        }

        注意: result_file 的存在即表示 agent 已完成。
        轮询: poll.py --label <label> --timeout <seconds>
        """
        prompt = task.get("prompt", task.get("description", ""))
        if not prompt:
            return {
                "mode": "spawn",
                "status": "error",
                "output": "No prompt provided for spawn mode",
                "executed_at": datetime.now().isoformat(),
            }

        # 生成唯一结果文件路径
        ts = int(datetime.now().timestamp())
        label = task.get("label", "spawn")
        result_file = task.get("result_file") or str(
            _Path(RESULTS_DIR) / f"spawn_{label}_{ts}.json"
        )
        task_file = str(_Path(QUEUE_DIR) / f"task_spawn_{label}_{ts}.json")

        # 写任务详情（供 spawned agent 读取）
        task_data = {
            "task_id": f"task_{label}_{ts}",
            "label": label,
            "prompt": prompt,
            "result_file": result_file,
            "task_file": task_file,
            "created_at": datetime.now().isoformat(),
        }
        _Path(QUEUE_DIR).mkdir(parents=True, exist_ok=True)
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)

        # sessions_spawn 调用方式（由 AI 执行）:
        # sessions_spawn(
        #     message=f"""你是 ClawSwarm agent。
        #     读取任务: {task_file}
        #     执行后写入: {result_file}
        #     格式: {{"status":"success","output":"...","completed_at":"..."}}
        #     """,
        #     agent_id=task.get("agent_id", "main"),
        #     model=task.get("model"),
        #     timeout=ctx.timeout_seconds,
        # )

        return {
            "mode": "spawn",
            "session_key": f"agent:main:spawn_{label}_{ts}",
            "task_file": task_file,
            "result_file": result_file,
            "agent_id": task.get("agent_id", "main"),
            "model": task.get("model"),
            "status": "spawned",
            "note": (
                f"Task written to {task_file}.\n"
                f"Call sessions_spawn to execute. Poll {result_file} for result."
            ),
            "executed_at": datetime.now().isoformat(),
        }
    
    async def _execute_fetch(self, ctx: ExecutionContext, task: dict) -> Any:
        """网页抓取 — 真实实现"""
        url = task.get("url")
        prompt = task.get("prompt", task.get("description", ""))

        # 如果没给 url 但有 prompt，从 prompt 中提取 URL
        if not url and prompt:
            import re
            # 提取第一个 http(s):// URL
            m = re.search(r'https?://[^\s\'"<>]+', prompt)
            url = m.group(0) if m else prompt.strip()

        if not url:
            raise ValueError("URL is required for fetch mode")

        # 确保有 scheme
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        max_chars = task.get("max_chars", 15000)
        timeout = task.get("timeout_seconds", ctx.timeout_seconds)

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    headers={"User-Agent": "ClawSwarm/0.2 (+https://github.com/liangfuliang541-pixel/clawswarm)"},
                ) as resp:
                    text = await resp.text(errors="replace")
                    # 简易 HTML → 纯文本
                    text = self._strip_html(text)
                    return {
                        "mode": "fetch",
                        "url": url,
                        "status_code": resp.status,
                        "content": text[:max_chars],
                        "length": len(text),
                        "fetched_at": datetime.now().isoformat(),
                    }
        except ImportError:
            # fallback: urllib
            import urllib.request
            req = urllib.request.Request(url, headers={
                "User-Agent": "ClawSwarm/0.2 (+https://github.com/liangfuliang541-pixel/clawswarm)"
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                text = self._strip_html(raw)
                return {
                    "mode": "fetch",
                    "url": url,
                    "status_code": resp.status,
                    "content": text[:max_chars],
                    "length": len(text),
                    "fetched_at": datetime.now().isoformat(),
                }

    @staticmethod
    def _strip_html(html: str) -> str:
        """简易 HTML → 纯文本（去标签，保留段落结构）"""
        import re
        # 去掉 script/style
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # 标签 → 换行
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?(p|div|h[1-6]|li|tr)[^>]*>', '\n', text, flags=re.IGNORECASE)
        # 去掉所有标签
        text = re.sub(r'<[^>]+>', '', text)
        # 解码常见 HTML 实体
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
        # 合并空白
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
    
    async def _execute_exec(self, ctx: ExecutionContext, task: dict) -> Any:
        """系统命令执行 — 真实实现"""
        command = task.get("command")
        if not command:
            raise ValueError("Command is required for exec mode")

        cwd = task.get("cwd")
        timeout = task.get("timeout_seconds", ctx.timeout_seconds)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Command timed out after {timeout}s: {command[:80]}")

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        return {
            "mode": "exec",
            "command": command,
            "exit_code": proc.returncode,
            "stdout": stdout_text[-10000:],  # 截断防止爆炸
            "stderr": stderr_text[-5000:],
            "executed_at": datetime.now().isoformat(),
        }
    
    async def _execute_python(self, ctx: ExecutionContext, task: dict) -> Any:
        """Python 代码执行 — 真实实现"""
        code = task.get("code")
        if not code:
            raise ValueError("Code is required for python mode")

        timeout = task.get("timeout_seconds", ctx.timeout_seconds)

        loop = asyncio.get_event_loop()
        output_capture = {"stdout": "", "stderr": ""}

        def _run():
            import io, sys, contextlib
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()

            namespace = {"__builtins__": __builtins__, "result": None}
            try:
                with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                    exec(code, namespace)
                output_capture["stdout"] = stdout_buf.getvalue()[-10000:]
                output_capture["stderr"] = stderr_buf.getvalue()[-5000:]
                output_capture["result"] = namespace.get("result")
            except Exception as e:
                output_capture["stderr"] = stderr_buf.getvalue()[-5000:]
                raise

        try:
            await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Python code timed out after {timeout}s")

        return {
            "mode": "python",
            "result": output_capture.get("result"),
            "stdout": output_capture["stdout"],
            "stderr": output_capture["stderr"],
            "executed_at": datetime.now().isoformat(),
        }
    
    async def _execute_workflow(self, ctx: ExecutionContext, task: dict) -> Any:
        """工作流执行"""
        steps = task.get("steps", [])
        results = []
        
        for i, step in enumerate(steps):
            step_ctx = ExecutionContext(
                task_id=f"{ctx.task_id}_step_{i}",
                node_id=ctx.node_id,
                mode=step.get("mode", "spawn"),
                config=step.get("config", {}),
            )

            result = await self._execute_mode(step_ctx, step)
            results.append(result)

            # 检查是否继续
            if step.get("stop_on_failure", False) and result != "done":
                break
        
        return {
            "mode": "workflow",
            "steps": len(steps),
            "results": results,
            "executed_at": datetime.now().isoformat(),
        }
    
    # ── 完成处理 ─────────────────────────────────────────────────────────
    
    def _complete(self, result: ExecutionResult):
        """任务完成处理"""
        self._running_tasks.pop(result.task_id, None)
        self._history.append(result)

        if result.status == "done":
            self._stats["success"] += 1
            self._trigger("on_success", result)
        elif result.status == "timeout":
            self._stats["timeout"] += 1
            self._trigger("on_timeout", result)
        else:
            self._stats["failed"] += 1
            self._trigger("on_failure", result)
    
    # ── 状态查询 ─────────────────────────────────────────────────────────
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            **self._stats,
            "running": len(self._running_tasks),
            "history_size": len(self._history),
        }
    
    def get_running(self) -> List[ExecutionContext]:
        """获取正在执行的任务"""
        return list(self._running_tasks.values())
    
    def get_history(self, limit: int = 100) -> List[ExecutionResult]:
        """获取历史记录"""
        return self._history[-limit:]
    
    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self._running_tasks:
            result = ExecutionResult(
                task_id=task_id,
                status="cancelled",
                error="Cancelled by user",
            )
            self._complete(result)
            return True
        return False


# ── 便捷函数 ─────────────────────────────────────────────────────────────

def create_executor(
    max_workers: int = 5,
    default_timeout: int = 300,
    enable_parallel: bool = True
) -> TaskExecutor:
    """创建执行器实例"""
    return TaskExecutor(
        max_workers=max_workers,
        default_timeout=default_timeout,
        enable_parallel=enable_parallel,
    )


async def execute_task(task: dict) -> ExecutionResult:
    """快速执行单个任务"""
    executor = create_executor()
    return await executor.execute(task)


async def execute_tasks(tasks: List[dict]) -> List[ExecutionResult]:
    """快速并行执行多个任务"""
    executor = create_executor()
    return await executor.execute_parallel(tasks)


# ── 测试 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def test():
        print("=" * 50)
        print("TaskExecutor 测试")
        print("=" * 50)
        
        # 创建执行器
        executor = TaskExecutor(default_timeout=30)
        
        # 注册回调
        executor.on("on_success", lambda r: print(f"✅ 成功: {r.task_id}"))
        executor.on("on_failure", lambda r: print(f"❌ 失败: {r.task_id} - {r.error}"))
        
        # 测试任务
        tasks = [
            {"id": "task_1", "mode": "spawn", "prompt": "测试任务1"},
            {"id": "task_2", "mode": "fetch", "url": "https://example.com"},
            {"id": "task_3", "mode": "exec", "command": "ls"},
        ]
        
        # 并行执行
        results = await executor.execute_parallel(tasks)
        
        # 打印结果
        print("\n结果:")
        for r in results:
            print(f"  {r.task_id}: {r.status.value} ({r.duration_seconds:.2f}s)")
        
        # 打印统计
        print(f"\n统计: {executor.get_stats()}")
    
    asyncio.run(test())
