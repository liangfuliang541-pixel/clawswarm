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
        "description": "启动一个 ClawSwarm 子龙虾执行任务。写入任务文件到队列，返回 task_id 和结果文件路径。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "任务描述（自然语言）",
                },
                "label": {
                    "type": "string",
                    "description": "唯一标签（用于结果聚合）",
                },
                "timeout": {
                    "type": "number",
                    "description": "超时秒数（默认300）",
                },
                "priority": {
                    "type": "number",
                    "description": "优先级1-10（默认5）",
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
        "description": "轮询等待指定标签的结果文件出现并读取结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "任务标签（匹配结果文件）",
                },
                "timeout": {
                    "type": "number",
                    "description": "轮询超时秒数（默认300）",
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
        "description": "提交任务到队列（不等待结果）。返回 task_id。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "任务描述",
                },
                "mode": {
                    "type": "string",
                    "description": "执行模式：spawn/fetch/exec/python（默认spawn）",
                },
                "priority": {
                    "type": "number",
                    "description": "优先级1-10（默认5）",
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
        "description": "获取 ClawSwarm 集群整体状态（节点数/在线数/指标）。",
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
            # Fallback: 列出 queue 目录中的节点信息
            return {
                "total": 0,
                "online": 0,
                "list": [],
                "note": "Monitor not available, returning empty node list",
            }
        except Exception as e:
            return {"error": str(e)}

    server.register_tool("clawswarm_nodes", {
        "description": "列出所有 ClawSwarm 节点及其状态。",
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
        "description": "读取多个标签对应的结果文件，聚合为一个输出。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "结果标签列表",
                },
            },
            "required": ["labels"],
        },
    }, handle_aggregate)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("ClawSwarm MCP Server starting...", file=sys.stderr)
    server = MCPStdioServer()
    setup_tools(server)
    print(f"Registered {len(server._tools)} tools: {list(server._tools.keys())}", file=sys.stderr)
    server.run()


if __name__ == "__main__":
    main()
