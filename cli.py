"""
ClawSwarm 命令行工具

用法:
    python cli.py status
    python cli.py add-task "任务描述"
    python cli.py list-tasks
    python cli.py start-node node1
    python cli.py run "搜索 X 并写报告"
"""

import os, sys, json, argparse, subprocess, threading, time
from datetime import datetime

from paths import BASE_DIR, QUEUE_DIR, IN_PROGRESS_DIR, RESULTS_DIR, AGENTS_DIR


# ── 命令: 状态 ─────────────────────────────────────────────────────────

def cmd_status(args):
    print("=" * 50)
    print("ClawSwarm 集群状态")
    print("=" * 50)

    for label, dir_path in [("待执行", QUEUE_DIR), ("执行中", IN_PROGRESS_DIR), ("已完成", RESULTS_DIR)]:
        count = len([f for f in os.listdir(dir_path)
                     if f.endswith(".json") and (label != "已完成" or f.startswith("r_"))]) \
                if os.path.exists(dir_path) else 0
        print(f"  {label}: {count}")

    if os.path.exists(AGENTS_DIR):
        agents = [f for f in os.listdir(AGENTS_DIR) if f.endswith(".json")]
        print(f"\n  节点数: {len(agents)}")
        for f in agents[:10]:
            with open(os.path.join(AGENTS_DIR, f), encoding="utf-8") as fp:
                try:
                    n = json.load(fp)
                    print(f"  - {n.get('id', f)}: {n.get('status', '?')}  "
                          f"caps={n.get('capabilities', [])}")
                except Exception:
                    pass

    print()
    return 0


# ── 命令: 添加任务 ─────────────────────────────────────────────────────

def cmd_add_task(args):
    task = {
        "id":          f"t_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "type":        args.type or "general",
        "description": args.description or args.task,
        "prompt":     args.prompt or args.task,
        "mode":       args.mode or "spawn",
        "priority":   args.priority or 1,
        "created_at": datetime.now().isoformat(),
    }
    os.makedirs(QUEUE_DIR, exist_ok=True)
    with open(os.path.join(QUEUE_DIR, f"{task['id']}.json"), "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    print(f"Task added: {task['id']} ({task['type']})")
    return 0


# ── 命令: 列出任务 ───────────────────────────────────────────────────

def cmd_list_tasks(args):
    print("任务列表\n" + "=" * 50)
    status_filter = args.status

    for label, dir_path, pattern in [
        ("待执行", QUEUE_DIR, ".json"),
        ("执行中", IN_PROGRESS_DIR, ".json"),
        ("已完成", RESULTS_DIR, "r_"),
    ]:
        if status_filter and status_filter not in label:
            continue
        if not os.path.exists(dir_path):
            continue
        files = [f for f in os.listdir(dir_path) if f.endswith(pattern)]
        print(f"\n{label} ({len(files)}):")
        for f in files[:10]:
            with open(os.path.join(dir_path, f), encoding="utf-8") as fp:
                t = json.load(fp)
                print(f"  {t.get('id', f)}: {t.get('description', '')[:50]}")
        if len(files) > 10:
            print(f"  ... 还有 {len(files) - 10} 个")

    print()
    return 0


# ── 命令: 启动节点 ───────────────────────────────────────────────────

def cmd_start_node(args):
    node_id = args.node_id
    print(f"启动节点: {node_id}")
    node_script = os.path.join(BASE_DIR, "swarm_node.py")

    # 从角色获取默认能力
    caps = list(args.capabilities)
    if not caps:
        # 默认用 all 能力
        caps = ["search", "write", "code", "read", "analyze", "report"]
        print(f"  无指定能力，使用默认: {caps}")
    else:
        # 映射角色名到能力
        role_map = {
            "researcher": ["search", "analyze"],
            "writer":     ["write"],
            "coder":      ["code", "write"],
            "analyzer":   ["analyze"],
            "reviewer":   ["read"],
            "planner":    ["search"],
            "all":        ["search", "write", "code", "read", "analyze", "report"],
        }
        # 如果指定了角色，展开为能力列表
        expanded = []
        for cap in caps:
            expanded.extend(role_map.get(cap, [cap]))
        caps = list(dict.fromkeys(expanded))  # 去重保持顺序

    proc = subprocess.Popen(
        [sys.executable, node_script, node_id] + caps,
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    )
    print(f"  PID {proc.pid}")
    time.sleep(3)
    agent_file = os.path.join(AGENTS_DIR, f"{node_id}.json")
    if os.path.exists(agent_file):
        n = json.load(open(agent_file, encoding="utf-8"))
        print(f"  registered: {n.get('status')}  caps={n.get('capabilities')}")
    return 0


# ── 命令: 运行编排任务 ───────────────────────────────────────────────

def cmd_run(args):
    from orchestrator import Orchestrator
    desc = args.description
    timeout = args.timeout or 120

    print("=" * 60)
    print("ClawSwarm Orchestrator")
    print("=" * 60)

    orc = Orchestrator(timeout=float(timeout))
    result = orc.run(desc)

    print("\n" + "=" * 60)
    print("Final Result:")
    print("=" * 60)
    print(result.final_output)

    if result.errors:
        print("\nWarnings:")
        for e in result.errors:
            print(f"  {e}")

    return 0 if result.success else 1


# ── 命令: 启动集群 ───────────────────────────────────────────────────

def cmd_start_cluster(args):
    print("启动集群...")
    from paths import ensure_dirs
    ensure_dirs()

    nodes = [
        ("claw_alpha", "search", "write", "code"),
        ("claw_beta",  "read",   "write"),
        ("claw_gamma", "search", "analyze", "report"),
    ]

    procs = {}
    for node_id, *caps in nodes:
        p = subprocess.Popen(
            [sys.executable,
             os.path.join(BASE_DIR, "swarm_node.py"),
             node_id] + caps,
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
        procs[node_id] = p
        print(f"  {node_id} started (PID {p.pid})")

    print(f"\n{len(nodes)} nodes running. Use 'python cli.py status' to monitor.")
    return 0


# ── 命令: 清理 ───────────────────────────────────────────────────────

def cmd_clean(args):
    print("清理中...")
    for name, path in [
        ("queue",      QUEUE_DIR),
        ("in_progress", IN_PROGRESS_DIR),
        ("results",     RESULTS_DIR),
    ]:
        if os.path.exists(path):
            count = len(os.listdir(path))
            if args.force:
                for f in os.listdir(path):
                    try:
                        os.remove(os.path.join(path, f))
                    except Exception:
                        pass
                print(f"  cleared {name}: {count} files")
            else:
                print(f"  {name}: {count} files (use --force)")
    return 0


# ── 命令: 单元测试 ───────────────────────────────────────────────────

def cmd_test(args):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v"],
        cwd=BASE_DIR,
    )
    return result.returncode


# ── 主函数 ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ClawSwarm CLI")
    sub = parser.add_subparsers(dest="cmd", help="可用命令")

    sub.add_parser("status",         help="集群状态").add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("add-task",   help="添加任务")
    p.add_argument("task",           help="任务描述")
    p.add_argument("-t", "--type",  help="任务类型 (fetch/analyze/report/code)")
    p.add_argument("-p", "--prompt",help="完整提示词")
    p.add_argument("-m", "--mode",  help="执行模式")
    p.add_argument("--priority", type=int)

    sub.add_parser("list-tasks",     help="列出任务").add_argument("-s", "--status", choices=["pending", "running", "done"])

    p = sub.add_parser("start-node", help="启动节点")
    p.add_argument("node_id",        help="节点 ID")
    p.add_argument("capabilities",   nargs="*", help="能力列表")

    sub.add_parser("start-cluster",  help="启动3节点集群")

    p = sub.add_parser("run",        help="编排执行高层任务")
    p.add_argument("description",    help="任务描述")
    p.add_argument("--timeout", type=float, help="超时秒数")

    p = sub.add_parser("clean",      help="清理队列")
    p.add_argument("-f", "--force",  action="store_true")

    sub.add_parser("test",           help="运行单元测试")

    args = parser.parse_args(sys.argv[1:])

    if not args.cmd:
        parser.print_help()
        return 0

    commands = {
        "status":       cmd_status,
        "add-task":     cmd_add_task,
        "list-tasks":   cmd_list_tasks,
        "start-node":   cmd_start_node,
        "start-cluster":cmd_start_cluster,
        "run":          cmd_run,
        "clean":        cmd_clean,
        "test":         cmd_test,
    }

    return commands.get(args.cmd, lambda _: parser.print_help() or 1)(args)


if __name__ == "__main__":
    sys.exit(main())
