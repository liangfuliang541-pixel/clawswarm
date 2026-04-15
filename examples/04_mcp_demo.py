#!/usr/bin/env python3
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
"""
ClawSwarm MCP Demo — 通过 MCP 协议调用 ClawSwarm

MCP (Model Context Protocol): Anthropic 主导的 AI 工具扩展标准
本脚本展示如何通过 Python stdio 调用 MCP 服务器

运行方法:
    python examples/04_mcp_demo.py

也可以直接通过 mcporter 调用:
    mcporter call --stdio -- node mcp_server.py clawswarm_spawn '{"prompt":"Hello"}'
"""

import json
import subprocess
import sys


def call_mcp_server(method: str, params: dict = None) -> dict:
    """通过 stdio 调用 MCP 服务器"""
    from pathlib import Path
    server_script = str(Path(__file__).parent.parent / "mcp_server.py")

    proc = subprocess.Popen(
        [sys.executable, server_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )

    # 先初始化
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "clawswarm-mcp-demo", "version": "1.0"},
        },
    }
    proc.stdin.write(json.dumps(init_req) + "\n")
    proc.stdin.flush()
    init_resp = json.loads(proc.stdout.readline())

    # 发送请求
    req_id = 2
    req = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    }
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()

    resp_line = proc.stdout.readline()
    resp = json.loads(resp_line)

    proc.stdin.close()
    proc.wait(timeout=5)

    if "result" in resp:
        return resp["result"]
    elif "error" in resp:
        return {"error": resp["error"]}
    return {}


def list_tools():
    """列出所有可用 MCP tools"""
    print("\n" + "=" * 50)
    print("ClawSwarm MCP Tools")
    print("=" * 50)

    result = call_mcp_server("tools/list")
    tools = result.get("tools", [])
    print(f"\nFound {len(tools)} tools:")
    for tool in tools:
        print(f"\n  [{tool['name']}]")
        print(f"    {tool['description']}")


def demo_spawn():
    """示例：spawn 一个任务"""
    print("\n" + "=" * 50)
    print("Demo: clawswarm_spawn")
    print("=" * 50)

    result = call_mcp_server("tools/call", {
        "name": "clawswarm_spawn",
        "arguments": {
            "prompt": "What is the capital of France?",
            "label": "demo_spawn",
            "timeout": 60,
        },
    })

    content = result.get("content", [{}])
    text = content[0].get("text", str(result))
    print(f"\n{text}")


def demo_submit():
    """示例：submit 一个任务"""
    print("\n" + "=" * 50)
    print("Demo: clawswarm_submit")
    print("=" * 50)

    result = call_mcp_server("tools/call", {
        "name": "clawswarm_submit",
        "arguments": {
            "prompt": "Search for the latest AI agent news",
            "mode": "spawn",
            "priority": 8,
        },
    })

    content = result.get("content", [{}])
    text = content[0].get("text", str(result))
    print(f"\n{text}")


def demo_status():
    """示例：获取集群状态"""
    print("\n" + "=" * 50)
    print("Demo: clawswarm_status")
    print("=" * 50)

    result = call_mcp_server("tools/call", {
        "name": "clawswarm_status",
        "arguments": {},
    })

    content = result.get("content", [{}])
    text = content[0].get("text", str(result))
    print(f"\n{text[:500]}")


def demo_nodes():
    """示例：列出节点"""
    print("\n" + "=" * 50)
    print("Demo: clawswarm_nodes")
    print("=" * 50)

    result = call_mcp_server("tools/call", {
        "name": "clawswarm_nodes",
        "arguments": {},
    })

    content = result.get("content", [{}])
    text = content[0].get("text", str(result))
    print(f"\n{text[:300]}")


if __name__ == "__main__":
    print("ClawSwarm MCP Demo")
    print("=" * 50)

    list_tools()
    demo_submit()
    demo_status()
    demo_nodes()

    print("\n" + "=" * 50)
    print("All MCP demos complete!")
    print("=" * 50)
