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
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
import traceback

from models import TaskStatus, TaskMode, ExecutionResult

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
        """启动子 Agent"""
        # 这里可以调用 sessions_spawn
        # 由于是异步占位实现，实际需要根据具体环境调整
        prompt = task.get("prompt", task.get("description", ""))
        model = task.get("model", "default")
        
        # 模拟执行
        await asyncio.sleep(0.1)
        
        return {
            "mode": "spawn",
            "prompt": prompt,
            "model": model,
            "executed_at": datetime.now().isoformat(),
        }
    
    async def _execute_fetch(self, ctx: ExecutionContext, task: dict) -> Any:
        """网页抓取"""
        url = task.get("url")
        if not url:
            raise ValueError("URL is required for fetch mode")
        
        max_chars = task.get("max_chars", 10000)
        
        # 这里可以调用 web_fetch
        # 模拟执行
        await asyncio.sleep(0.1)
        
        return {
            "mode": "fetch",
            "url": url,
            "max_chars": max_chars,
            "fetched_at": datetime.now().isoformat(),
        }
    
    async def _execute_exec(self, ctx: ExecutionContext, task: dict) -> Any:
        """系统命令执行"""
        command = task.get("command")
        if not command:
            raise ValueError("Command is required for exec mode")
        
        cwd = task.get("cwd")
        env = task.get("env", {})
        
        # 模拟执行
        await asyncio.sleep(0.1)
        
        return {
            "mode": "exec",
            "command": command,
            "cwd": cwd,
            "executed_at": datetime.now().isoformat(),
        }
    
    async def _execute_python(self, ctx: ExecutionContext, task: dict) -> Any:
        """Python 代码执行"""
        code = task.get("code")
        if not code:
            raise ValueError("Code is required for python mode")
        
        # 注意：实际执行 Python 代码需要沙箱环境
        # 这里仅做模拟
        await asyncio.sleep(0.1)
        
        return {
            "mode": "python",
            "code_preview": code[:100] + "..." if len(code) > 100 else code,
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
