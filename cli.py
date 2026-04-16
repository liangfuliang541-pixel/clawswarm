"""
ClawSwarm CLI — 龙虾集群命令行管理工具

用法:
    python cli.py relay start [--port 18080]     启动 relay server
    python cli.py relay status                   查看 relay 状态
    python cli.py node register <node_id>        注册节点
    python cli.py node list                      列出所有节点
    python cli.py node exec <node_id> <cmd>      在节点执行命令
    python cli.py node discover                   发现节点
    python cli.py pair generate                   生成本机配对码
    python cli.py pair connect <code>             用配对码连接
    python cli.py tunnel create                   创建 serveo 隧道暴露 relay
    python cli.py health                          集群健康检查
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))
from relay_client import RelayClient, RemoteRelay


# ── 配置 ────────────────────────────────────────────────────────────────

RELAY_URL = os.environ.get("CLAWSWARM_RELAY_URL", "http://localhost:18080")
GATEWAY_URL = os.environ.get("CLAWSWARM_GATEWAY_URL", "http://localhost:28789")
GATEWAY_TOKEN = os.environ.get("CLAWSWARM_GATEWAY_TOKEN", "")
THIS_NODE_ID = os.environ.get("CLAWSWARM_NODE_ID", "cli-agent")
THIS_CAPABILITIES = os.environ.get("CLAWSWARM_CAPABILITIES", "read,write,code,search").split(",")


# ── 工具函数 ────────────────────────────────────────────────────────────

def c(url: str, path: str) -> dict:
    """GET 请求"""
    try:
        with urllib.request.urlopen(f"{url}{path}", timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def cp(url: str, path: str, data: dict = None) -> dict:
    """POST JSON 请求"""
    body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{url}{path}", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        try:
            return json.loads(str(e))
        except Exception:
            return {"error": str(e)}


def ok(result: dict) -> bool:
    return "error" not in result


def print_node(n: dict):
    status_icon = "🟢" if n.get("status") == "online" else "🔴"
    print(f"  {status_icon} {n['node_id']}: {n.get('name','')}")
    caps = n.get("capabilities", [])
    print(f"       能力: {', '.join(caps)}")
    if n.get("gateway_url"):
        print(f"       Gateway: {n['gateway_url']}")
    print(f"       注册: {n.get('registered_at', '?')} | 最后在线: {n.get('last_seen', '?')}")
    print()


# ── 命令 ───────────────────────────────────────────────────────────────

def cmd_relay_start(args):
    """启动 relay server"""
    import threading
    
    sys.path.insert(0, str(Path(__file__).parent))
    from relay_server import run
    
    print(f"🚀 启动 Relay Server 于 :{args.port} ...")
    print(f"   数据目录: {Path(__file__).parent / 'relay_data'}")
    print(f"   暴露到公网: 运行 serveo 隧道命令:")
    print()
    print(f"   ssh -o ServerAliveInterval=30 -R 0:localhost:{args.port} serveo.net")
    print()
    
    # 启动 server（阻塞）
    run(port=args.port, host=args.host)


def cmd_relay_status(args):
    """查看 relay 状态"""
    result = c(RELAY_URL, "/health")
    if ok(result):
        print(f"✅ Relay 在线")
        print(f"   启动时间: {result.get('started_at', '?')}")
        print(f"   运行时间: {result.get('uptime_seconds', 0)}s")
        print(f"   已注册节点: {result.get('nodes_registered', 0)}")
        print(f"   请求数: {result.get('requests', 0)}")
    else:
        print(f"❌ Relay 离线: {result}")
        sys.exit(1)


def cmd_node_register(args):
    """注册节点到 relay"""
    client = RelayClient(
        relay_url=RELAY_URL,
        node_id=args.node_id or THIS_NODE_ID,
        gateway_url=args.gateway_url or GATEWAY_URL,
        token=args.token or GATEWAY_TOKEN,
        capabilities=args.capabilities.split(",") if args.capabilities else THIS_CAPABILITIES,
    )
    result = client.register()
    if ok(result):
        print(f"✅ 节点注册成功: {args.node_id}")
        print(f"   Gateway: {args.gateway_url or GATEWAY_URL}")
    else:
        print(f"❌ 注册失败: {result}")
        sys.exit(1)


def cmd_node_list(args):
    """列出所有节点"""
    result = c(RELAY_URL, "/nodes")
    nodes = result.get("nodes", [])
    print(f"📡 已注册节点 ({len(nodes)}):\n")
    if not nodes:
        print("   (空)")
    for n in nodes:
        print_node(n)


def cmd_node_exec(args):
    """在指定节点执行命令"""
    # 先获取节点信息
    node_info = c(RELAY_URL, f"/discover/{args.node_id}")
    if "error" in node_info:
        print(f"❌ 节点不存在: {args.node_id}")
        sys.exit(1)
    
    target_url = node_info.get("node", {}).get("gateway_url", "")
    if not target_url:
        print(f"❌ 节点 gateway_url 为空")
        sys.exit(1)
    
    print(f"⚡ 在 {args.node_id} 执行: {args.command}")
    
    # 通过 relay 发送命令
    resp = cp(RELAY_URL, f"/cmd/{args.node_id}", {"command": args.command})
    if "error" in resp:
        print(f"❌ 发送失败: {resp}")
        sys.exit(1)
    
    print(f"   命令已提交，等待结果 (超时 {args.timeout}s)...")
    
    deadline = time.time() + (args.timeout or 60)
    while time.time() < deadline:
        result_data = c(RELAY_URL, f"/result/{args.node_id}")
        if result_data and "result" in result_data:
            print(f"\n✅ 结果 ({result_data.get('status', 'ok')}):")
            print(result_data["result"])
            return
        time.sleep(1)
    
    print(f"⏰ 超时")


def cmd_node_discover(args):
    """发现并显示所有在线节点"""
    client = RelayClient(
        relay_url=RELAY_URL,
        node_id=THIS_NODE_ID,
        gateway_url=GATEWAY_URL,
        token=GATEWAY_TOKEN,
        capabilities=THIS_CAPABILITIES,
    )
    
    print(f"🔍 从 {RELAY_URL} 发现节点...\n")
    
    all_nodes = client.discover_nodes()
    online = [n for n in all_nodes if n.get("status") == "online"]
    offline = [n for n in all_nodes if n.get("status") != "online"]
    
    print(f"🟢 在线 ({len(online)}):")
    if not online:
        print("   (无)")
    for n in online:
        print_node(n)
    
    print(f"🔴 离线 ({len(offline)}):")
    if not offline:
        print("   (无)")
    for n in offline:
        print_node(n)


def cmd_pair_generate(args):
    """生成本机配对码"""
    client = RelayClient(
        relay_url=RELAY_URL,
        node_id=args.node_id or THIS_NODE_ID,
        gateway_url=GATEWAY_URL,
        token=GATEWAY_TOKEN,
        capabilities=THIS_CAPABILITIES,
    )
    
    result = c(RELAY_URL, f"/pairing/generate?node_id={args.node_id or THIS_NODE_ID}")
    if "error" in result:
        print(f"❌ 生成失败: {result}")
        sys.exit(1)
    
    code = result["code"]
    print(f"\n🎯 配对码生成成功!")
    print(f"\n   代码: {code}")
    print(f"   有效期: 5 分钟")
    print(f"\n分享给要连接的龙虾，输入以下命令:")
    print(f"\n   python cli.py pair connect {code}")
    print()


def cmd_pair_connect(args):
    """使用配对码连接"""
    client = RelayClient(
        relay_url=RELAY_URL,
        node_id=THIS_NODE_ID,
        gateway_url=GATEWAY_URL,
        token=GATEWAY_TOKEN,
        capabilities=THIS_CAPABILITIES,
    )
    
    print(f"🔗 使用配对码 {args.code} 连接...")
    result = cp(RELAY_URL, f"/pairing/connect/{args.code}", {
        "node_id": THIS_NODE_ID,
        "node_info": {
            "gateway_url": GATEWAY_URL,
            "token": GATEWAY_TOKEN,
            "capabilities": THIS_CAPABILITIES,
        }
    })
    
    if "error" in result:
        print(f"❌ 连接失败: {result['error']} - {result.get('message', '')}")
        sys.exit(1)
    
    print(f"✅ 连接成功!")
    partner = result.get("partner", {})
    print(f"\n   已连接: {partner.get('node_id')}")
    print()


def cmd_health(args):
    """集群健康检查"""
    print(f"🏥 ClawSwarm 健康检查\n")
    
    # 1. Relay 状态
    print(f"[1/3] Relay Server")
    result = c(RELAY_URL, "/health")
    if ok(result):
        print(f"       ✅ 在线 (运行 {result.get('uptime_seconds', 0)}s)")
    else:
        print(f"       ❌ 离线")
    
    # 2. 节点列表
    print(f"\n[2/3] 注册节点")
    nodes_result = c(RELAY_URL, "/nodes")
    nodes = nodes_result.get("nodes", [])
    online = [n for n in nodes if n.get("status") == "online"]
    print(f"       总数: {len(nodes)} | 在线: {len(online)}")
    
    # 3. 端到端测试
    print(f"\n[3/3] 端到端测试")
    for n in online:
        if n["node_id"] == THIS_NODE_ID:
            continue
        print(f"       测试 {n['node_id']}...")
        test_result = cp(RELAY_URL, f"/cmd/{n['node_id']}", {"command": "echo pong"})
        if ok(test_result):
            print(f"       ✅ {n['node_id']} 响应正常")
        else:
            print(f"       ❌ {n['node_id']} 无响应")


def cmd_tunnel_create(args):
    """生成 serveo 隧道命令"""
    port = args.port or 18080
    subdomain = args.subdomain or f"clawswarm-{THIS_NODE_ID[:8]}"
    
    cmd = f"ssh -o ServerAliveInterval=30 -o StrictHostKeyChecking=no -R 0:localhost:{port} {subdomain}@serveo.net"
    
    print(f"🔗 Serveo 隧道命令:\n")
    print(f"   {cmd}")
    print(f"\n📋 在 VM 上运行以上命令，relay server 就暴露到公网了。")
    print(f"   公网地址: https://{subdomain}.serveousercontent.com")
    print(f"\n⚠️  隧道 subdomain 每次重启会变，记得更新配置!")
    print(f"\n💡 持久化: 把命令保存为脚本，加入 systemd/crontab 自动重连")


# ── 主入口 ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ClawSwarm CLI", prog="python cli.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    
    # relay 子命令
    relay = sub.add_parser("relay", help="Relay Server 管理")
    relay_sub = relay.add_subparsers(dest="subcmd", required=True)
    
    r_start = relay_sub.add_parser("start", help="启动 relay server")
    r_start.add_argument("--port", type=int, default=18080)
    r_start.add_argument("--host", default="0.0.0.0")
    r_start.set_defaults(func=cmd_relay_start)
    
    r_status = relay_sub.add_parser("status", help="查看 relay 状态")
    r_status.set_defaults(func=cmd_relay_status)
    
    # node 子命令
    node = sub.add_parser("node", help="节点管理")
    node_sub = node.add_subparsers(dest="subcmd", required=True)
    
    n_reg = node_sub.add_parser("register", help="注册节点")
    n_reg.add_argument("node_id", nargs="?", default=None)
    n_reg.add_argument("--gateway-url")
    n_reg.add_argument("--token")
    n_reg.add_argument("--capabilities")
    n_reg.set_defaults(func=cmd_node_register)
    
    n_list = node_sub.add_parser("list", help="列出节点")
    n_list.set_defaults(func=cmd_node_list)
    
    n_exec = node_sub.add_parser("exec", help="在节点执行命令")
    n_exec.add_argument("node_id")
    n_exec.add_argument("command", nargs="...")
    n_exec.add_argument("--timeout", type=int, default=60)
    n_exec.set_defaults(func=cmd_node_exec)
    
    n_disc = node_sub.add_parser("discover", help="发现节点")
    n_disc.set_defaults(func=cmd_node_discover)
    
    # pair 子命令
    pair = sub.add_parser("pair", help="节点配对")
    pair_sub = pair.add_subparsers(dest="subcmd", required=True)
    
    p_gen = pair_sub.add_parser("generate", help="生成本机配对码")
    p_gen.add_argument("--node-id", default=None)
    p_gen.set_defaults(func=cmd_pair_generate)
    
    p_conn = pair_sub.add_parser("connect", help="使用配对码连接")
    p_conn.add_argument("code")
    p_conn.set_defaults(func=cmd_pair_connect)
    
    # health
    h = sub.add_parser("health", help="健康检查")
    h.set_defaults(func=cmd_health)
    
    # tunnel
    t = sub.add_parser("tunnel", help="serveo 隧道")
    t_sub = t.add_subparsers(dest="subcmd", required=True)
    t_create = t_sub.add_parser("create", help="生成隧道命令")
    t_create.add_argument("--port", type=int, default=18080)
    t_create.add_argument("--subdomain")
    t_create.set_defaults(func=cmd_tunnel_create)
    
    args = parser.parse_args()
    
    # 处理 exec 命令的 "..." 收集
    if hasattr(args, 'command') and isinstance(args.command, list):
        args.command = " ".join(args.command)
    
    args.func(args)


if __name__ == "__main__":
    main()
