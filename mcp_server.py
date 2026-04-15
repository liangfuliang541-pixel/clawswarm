"""
ClawSwarm MCP Server — 让其他 Agent 通过 MCP 协议调用 ClawSwarm

MCP (Model Context Protocol): Anthropic 主导的 AI 工具扩展标准
这个服务器把 ClawSwarm 的核心能力暴露为 MCP tools

运行:
    python mcp_server.py
    或: node .../mcp-server.js (通过 mcporter 调用)

MCP tools:
    clawswarm_spawn      — 启动子龙虾执行任务
    clawswarm_poll       — 轮询等待结果
    clawswarm_submit     — 提交任务到队列
    clawswarm_status     — 获取集群状态
    clawswarm_nodes      — 列出所有节点
    clawswarm_aggregate  — 聚合多个结果
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 项目路径 ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── MCP 协议基础 ────────────────────────────────────────────────────────

class MCPStdioServer:
    """基于 stdio 的 MCP 服务器（JSON-RPC over stdin/stdout）"""

    def __init__(self):
        self._tools: Dict[str, dict] = {}
        self._results_dir = BASE_DIR / "swarm_data" / "results"
        self._queue_dir = BASE_DIR / "swarm_data" / "queue"

    def register_tool(self, name: str, schema: dict, handler):
        """注册一个 MCP tool"""
        self._tools[name] = {
            "name": name,
            "description": schema.get("description", ""),
            "inputSchema": schema.get("inputSchema", {"type": "object", "properties": {}}),
            "handler": handler,
        }

    def _read_request(self) -> Optional[dict]:
        """从 stdin 读取一行 JSON-RPC 请求"""
        try:
            line = sys.stdin.readline()
            if not line:
                return None
            return json.loads(line.strip())
        except (json.JSONDecodeError, EOFError):
            return None

    def _send_response(self, resp: dict):
        """发送 JSON-RPC 响应到 stdout"""
        print(json.dumps(resp, ensure_ascii=False), flush=True)

    def _send_result(self, req_id: Any, result: Any):
        self._send_response({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _send_error(self, req_id: Any, code: int, message: str):
        self._send_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

    def _send_notification(self, method: str, params: dict):
        self._send_response({"jsonrpc": "2.0", "method": method, "params": params})

    def _send_tools_list(self, req_id: Any):
        tools = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
            }
            for name, spec in self._tools.items()
        ]
        self._send_result(req_id, {"tools": tools})

    def _send_tools_called(self, req_id: Any, content: List[dict]):
        self._send_result(req_id, {"content": content})

    def _call_tool(self, name: str, arguments: dict) -> dict:
        """调用已注册的 tool"""
        if name not in self._tools:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}]}

        handler = self._tools[name]["handler"]
        try:
            result = handler(arguments)
            if isinstance(result, str):
                return {"content": [{"type": "text", "text": result}]}
            elif isinstance(result, dict):
                if "error" in result:
                    return {"content": [{"type": "text", "text": f"Error: {result['error']}"}]}
                return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}
            else:
                return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Exception: {type(e).__name__}: {e}"}]}

    def run(self):
        """主循环：读取请求 → 处理 → 响应"""
        # 首先发送 initialize 响应所需的 capabilities
        initialized = False

        while True:
            req = self._read_request()
            if req is None:
                break

            method = req.get("method", "")
            req_id = req.get("id")

            if method == "initialize":
                # MCP 初始化
                self._send_result(req_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": True},
                    },
                    "serverInfo": {
                        "name": "clawswarm",
                        "version": "0.7.0",
                    },
                })
                initialized = True

            elif method == "notifications/initialized":
                # 客户端初始化完成通知
                pass

            elif method == "tools/list":
                self._send_tools_list(req_id)

            elif method == "tools/call":
                tool_name = req.get("params", {}).get("name", "")
                arguments = req.get("params", {}).get("arguments", {})
                result = self._call_tool(tool_name, arguments)
                self._send_tools_called(req_id, result["content"])

            elif method == "ping":
                self._send_result(req_id, {})

            else:
                if req_id is not None:
                    self._send_error(req_id, -32601, f"Method not found: {method}")


# ── ClawSwarm MCP Tools ───────────────────────────────────────────────

def setup_tools(server: MCPStdioServer):
    """注册所有 ClawSwarm MCP tools"""

    # 1. clawswarm_spawn — 启动子龙虾
    def handle_spawn(args: dict) -> dict:
        """启动一个子龙虾执行任务"""
        prompt = args.get("prompt", "")
        label = args.get("label", f"mcp_{int(time.time())}")
        timeout = args.get("timeout", 300)

        if not prompt:
            return {"error": "prompt is required"}

        ts = int(time.time())
        task_id = f"mcp_{label}_{ts}"
        task_file = server._queue_dir / f"task_{task_id}.json"
        result_file = server._results_dir / f"r_{task_id}.json"

        task_file.parent.mkdir(parents=True, exist_ok=True)
        task = {
            "id": task_id,
            "prompt": prompt,
            "mode": "spawn",
            "priority": args.get("priority", 5),
            "capabilities": args.get("capabilities", []),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(task, f, ensure_ascii=False, indent=2)

        return {
            "task_id": task_id,
            "status": "spawned",
            "task_file": str(task_file),
            "result_file": str(result_file),
            "poll_url": f"clawswarm_poll(label='{label}', timeout={timeout})",
        }

    server.register_tool("clawswarm_spawn", {
        "description": "Launch a ClawSwarm sub-agent task. Writes task file to queue, returns task_id and result file path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Task description (natural language)",
                },
                "label": {
                    "type": "string",
                    "description": "Unique label (for result aggregation)",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout seconds (default 300)",
                },
                "priority": {
                    "type": "number",
                    "description": "Priority 1-10 (default 5)",
                },
            },
            "required": ["prompt"],
        },
    }, handle_spawn)

    # 2. clawswarm_poll — 轮询等待结果
    def handle_poll(args: dict) -> dict:
        """轮询等待结果文件"""
        label = args.get("label", "")
        timeout = args.get("timeout", 300)
        ts_start = time.time()

        if not label:
            return {"error": "label is required"}

        while time.time() - ts_start < timeout:
            # 扫描 results 目录找匹配文件
            for rf in server._results_dir.glob(f"r_*{label}*.json"):
                try:
                    with open(rf, encoding="utf-8") as f:
                        result = json.load(f)
                    return {
                        "status": result.get("status", "unknown"),
                        "output": result.get("output", result.get("error", "")),
                        "result_file": str(rf),
                        "elapsed": round(time.time() - ts_start, 1),
                    }
                except Exception:
                    pass
            time.sleep(2)

        return {
            "status": "timeout",
            "label": label,
            "timeout": timeout,
        }

    server.register_tool("clawswarm_poll", {
        "description": "Poll for result file matching the given label.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "Task label (matches result files)",
                },
                "timeout": {
                    "type": "number",
                    "description": "Poll timeout seconds (default 300)",
                },
            },
            "required": ["label"],
        },
    }, handle_poll)

    # 3. clawswarm_submit — 提交任务
    def handle_submit(args: dict) -> dict:
        """直接提交任务到队列"""
        prompt = args.get("prompt", "")
        mode = args.get("mode", "spawn")
        priority = args.get("priority", 5)

        if not prompt:
            return {"error": "prompt is required"}

        ts = int(time.time())
        task_id = f"task_{ts}"
        task_file = server._queue_dir / f"task_{task_id}.json"

        task_file.parent.mkdir(parents=True, exist_ok=True)
        task = {
            "id": task_id,
            "prompt": prompt,
            "mode": mode,
            "priority": priority,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(task, f, ensure_ascii=False, indent=2)

        return {
            "task_id": task_id,
            "status": "submitted",
            "task_file": str(task_file),
            "mode": mode,
        }

    server.register_tool("clawswarm_submit", {
        "description": "Submit task to queue (no wait). Returns task_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Task description",
                },
                "mode": {
                    "type": "string",
                    "description": "Execution mode: spawn/fetch/exec/python (default spawn)",
                },
                "priority": {
                    "type": "number",
                    "description": "Priority 1-10 (default 5)",
                },
            },
            "required": ["prompt"],
        },
    }, handle_submit)

    # 4. clawswarm_status — 集群状态
    def handle_status(args: dict) -> dict:
        """获取集群整体状态"""
        try:
            from monitor import MonitorService
            monitor = MonitorService()
            return monitor.get_status()
        except ImportError:
            return {
                "error": "ClawSwarm monitor not available",
                "queue_dir": str(server._queue_dir),
                "results_dir": str(server._results_dir),
            }
        except Exception as e:
            return {"error": str(e)}

    server.register_tool("clawswarm_status", {
        "description": "Get ClawSwarm cluster overall status (nodes/metrics).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    }, handle_status)

    # 5. clawswarm_nodes — 节点列表
    def handle_nodes(args: dict) -> dict:
        """列出所有注册节点"""
        try:
            from monitor import MonitorService
            monitor = MonitorService()
            status = monitor.get_status()
            return status.get("nodes", {})
        except ImportError:
            return {
                "total": 0,
                "online": 0,
                "list": [],
                "note": "Monitor not available",
            }
        except Exception as e:
            return {"error": str(e)}

    server.register_tool("clawswarm_nodes", {
        "description": "List all ClawSwarm nodes and their status.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    }, handle_nodes)

    # 6. clawswarm_aggregate — 聚合结果
    def handle_aggregate(args: dict) -> dict:
        """读取多个结果文件并聚合"""
        labels = args.get("labels", [])
        if not labels:
            return {"error": "labels is required"}

        results = {}
        for label in labels:
            found = False
            for rf in sorted(server._results_dir.glob(f"r_*{label}*.json"), key=lambda p: p.stat().st_mtime):
                try:
                    with open(rf, encoding="utf-8") as f:
                        data = json.load(f)
                    results[label] = {
                        "status": data.get("status", "unknown"),
                        "output": data.get("output", data.get("error", "")),
                        "file": str(rf),
                    }
                    found = True
                    break
                except Exception:
                    pass
            if not found:
                results[label] = {"status": "not_found", "error": f"No result file for label: {label}"}

        return {
            "aggregated": results,
            "total": len(labels),
            "found": sum(1 for v in results.values() if v.get("status") != "not_found"),
        }

    server.register_tool("clawswarm_aggregate", {
        "description": "Read multiple label-matched result files and aggregate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Result label list",
                },
            },
            "required": ["labels"],
        },
    }, handle_aggregate)

    # 7. clawswarm_dead_letter — 死信队列
    def handle_dead_letter(args: dict) -> dict:
        """查看/重试/清理死信队列"""
        action = args.get("action", "list")
        reason = args.get("reason")
        entry_id = args.get("entry_id")
        limit = args.get("limit", 20)

        try:
            import dead_letter
            if action == "list":
                return dead_letter.list_entries(reason=reason, limit=limit)
            elif action == "retry":
                if not entry_id:
                    return {"error": "entry_id required for retry"}
                task_id = dead_letter.retry(entry_id)
                return {"retried": True, "new_task_id": task_id} if task_id else {"error": "Entry not found"}
            elif action == "purge":
                count = dead_letter.purge(entry_id=entry_id, reason=reason)
                return {"purged": count}
            elif action == "stats":
                return dead_letter.stats()
            else:
                return {"error": f"Unknown action: {action}. Use list/retry/purge/stats"}
        except ImportError:
            return {"error": "dead_letter module not available"}
        except Exception as e:
            return {"error": str(e)}

    server.register_tool("clawswarm_dead_letter", {
        "description": "Manage dead letter queue (failed/timeout tasks). Actions: list, retry, purge, stats.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "retry", "purge", "stats"],
                    "description": "DLQ action (default: list)",
                },
                "entry_id": {
                    "type": "string",
                    "description": "Specific entry ID (for retry/purge)",
                },
                "reason": {
                    "type": "string",
                    "description": "Filter by reason (for list/purge)",
                },
                "limit": {
                    "type": "number",
                    "description": "Max entries to return (default 20)",
                },
            },
        },
    }, handle_dead_letter)

    # 8. clawswarm_health — 节点健康评分
    def handle_health(args: dict) -> dict:
        """计算节点健康评分"""
        node_id = args.get("node_id", "unknown")
        cpu = args.get("cpu")
        memory = args.get("memory")
        success = args.get("successful_tasks", 0)
        failed = args.get("failed_tasks", 0)
        response_ms = args.get("avg_response_ms")

        try:
            import health_scorer
            report = health_scorer.compute_health(
                node_id=node_id,
                cpu_percent=cpu,
                memory_percent=memory,
                successful_tasks=success,
                failed_tasks=failed,
                avg_response_ms=response_ms,
            )
            return {
                "node_id": report.node_id,
                "score": report.score,
                "level": report.level,
                "breakdown": report.breakdown,
                "recommendation": report.recommendation,
                "should_accept_tasks": report.should_accept_tasks,
            }
        except ImportError:
            return {"error": "health_scorer module not available"}
        except Exception as e:
            return {"error": str(e)}

    server.register_tool("clawswarm_health", {
        "description": "Compute node health score (0-100) with breakdown. Levels: healthy/degraded/warning/critical.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "Node ID",
                },
                "cpu": {
                    "type": "number",
                    "description": "CPU percent (0-100)",
                },
                "memory": {
                    "type": "number",
                    "description": "Memory percent (0-100)",
                },
                "successful_tasks": {
                    "type": "number",
                    "description": "Count of successful tasks",
                },
                "failed_tasks": {
                    "type": "number",
                    "description": "Count of failed tasks",
                },
                "avg_response_ms": {
                    "type": "number",
                    "description": "Average response time in ms",
                },
            },
        },
    }, handle_health)

    # 9. clawswarm_remote_exec — 跨公网节点执行
    def handle_remote_exec(args: dict) -> dict:
        """
        通过 HTTP Relay 在远程 OpenClaw 节点上执行命令。
        
        用于跨公网节点控制（两台机器不在同一局域网时）。
        原理：POST /cmd → 远程执行 → GET /result 取结果
        
        使用步骤：
        1. 先调用 clawswarm_remote_register 注册节点
        2. 再用本工具执行命令
        """
        node_id = args.get("node_id")
        command = args.get("command", "")
        relay_url = args.get("relay_url")
        wait = args.get("wait", True)
        timeout = args.get("timeout", 60)

        if not command:
            return {"error": "command is required"}

        # 确定 relay_url
        if relay_url:
            relay = None
            target_node_id = None
        elif node_id:
            try:
                from relay_client import RemoteNodeManager, RemoteRelay
                mgr = RemoteNodeManager()
                node = mgr.get_node(node_id)
                if not node:
                    return {"error": f"Node not found: {node_id}. Use clawswarm_remote_register first."}
                relay = node.relay
                target_node_id = node_id
            except ImportError:
                return {"error": "relay_client module not available"}
        else:
            return {"error": "node_id or relay_url is required"}

        try:
            if relay:
                result = relay.exec(command, wait=wait, poll_interval=2)
            else:
                relay = RemoteRelay(relay_url)
                result = relay.exec(command, wait=wait, poll_interval=2)
                target_node_id = "direct"

            return {
                "node_id": target_node_id,
                "relay_url": relay.relay_url if relay else relay_url,
                "status": result["status"],
                "output": result["output"],
                "elapsed_seconds": result["elapsed"],
                "command": command,
            }
        except Exception as e:
            return {"error": f"Relay error: {e}"}

    server.register_tool("clawswarm_remote_exec", {
        "description": "Execute command on a remote OpenClaw node via HTTP relay. "
                       "Use clawswarm_remote_register first to register the node. "
                       "Supports cross-network execution when nodes are not on the same LAN.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "Pre-registered node ID (from clawswarm_remote_register)",
                },
                "relay_url": {
                    "type": "string",
                    "description": "Direct relay URL (e.g. https://xxxx.serveo.net) if node_id not registered",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to execute on the remote node",
                },
                "wait": {
                    "type": "boolean",
                    "description": "Wait for result (default True). Set False for fire-and-forget.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default 60)",
                },
            },
            "required": ["command"],
        },
    }, handle_remote_exec)

    # 10. clawswarm_remote_register — 注册远程节点
    def handle_remote_register(args: dict) -> dict:
        """将远程 OpenClaw 节点注册到 ClawSwarm 集群"""
        node_id = args.get("node_id")
        relay_url = args.get("relay_url")
        name = args.get("name")
        capabilities = args.get("capabilities", ["shell", "general"])

        if not node_id or not relay_url:
            return {"error": "node_id and relay_url are required"}

        try:
            from relay_client import RemoteNode
            node = RemoteNode(
                node_id=node_id,
                relay_url=relay_url,
                name=name or node_id,
                capabilities=capabilities,
            )
            result = node.register()
            # 测试连通性
            if node.relay.ping():
                result["connection_test"] = "ok"
            else:
                result["connection_test"] = "failed"
            return result
        except ImportError:
            return {"error": "relay_client module not available"}
        except Exception as e:
            return {"error": str(e)}

    server.register_tool("clawswarm_remote_register", {
        "description": "Register a remote OpenClaw node via HTTP relay tunnel. "
                       "The relay must be set up on the remote node first (serveo.net SSH tunnel + relay script). "
                       "After registration, use clawswarm_remote_exec to run commands on it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "Unique node ID (e.g. kimi-claw-01)",
                },
                "relay_url": {
                    "type": "string",
                    "description": "HTTP relay public URL (e.g. https://xxxx.serveo.net)",
                },
                "name": {
                    "type": "string",
                    "description": "Display name for the node",
                },
                "capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Node capabilities (default: ['shell', 'general'])",
                },
            },
            "required": ["node_id", "relay_url"],
        },
    }, handle_remote_register)

    # 11. clawswarm_remote_list — 列出已注册远程节点
    def handle_remote_list(args: dict) -> dict:
        """列出所有已注册的远程节点"""
        try:
            from relay_client import RemoteNodeManager
            mgr = RemoteNodeManager()
            nodes = mgr.list_nodes()
            return {
                "total": len(nodes),
                "nodes": nodes,
            }
        except ImportError:
            return {"error": "relay_client module not available"}
        except Exception as e:
            return {"error": str(e)}

    server.register_tool("clawswarm_remote_list", {
        "description": "List all registered remote nodes and their status.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    }, handle_remote_list)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("ClawSwarm MCP Server starting...", file=sys.stderr)
    server = MCPStdioServer()
    setup_tools(server)
    print(f"Registered {len(server._tools)} tools: {list(server._tools.keys())}", file=sys.stderr)
    server.run()


if __name__ == "__main__":
    main()
