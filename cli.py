"""
ClawSwarm 命令行工具

提供便捷的 CLI 命令来管理集群

用法:
    python cli.py status
    python cli.py add-task "任务描述"
    python cli.py list-nodes
    python cli.py start-node node1
"""

import os
import sys
import json
import argparse
import asyncio
from datetime import datetime
from pathlib import Path

# 添加项目根目录
SWARM_DIR = r"D:\claw\swarm"

# ── 命令: 状态 ─────────────────────────────────────────────────────

def cmd_status(args):
    """查看集群状态"""
    print("=" * 50)
    print("ClawSwarm 集群状态")
    print("=" * 50)
    
    # 读取队列
    queue_dir = os.path.join(SWARM_DIR, "queue")
    in_progress_dir = os.path.join(SWARM_DIR, "in_progress")
    results_dir = os.path.join(SWARM_DIR, "results")
    agents_dir = os.path.join(SWARM_DIR, "agents")
    
    queue_count = len([f for f in os.listdir(queue_dir) if f.endswith(".json")]) if os.path.exists(queue_dir) else 0
    in_progress_count = len([f for f in os.listdir(in_progress_dir) if f.endswith(".json")]) if os.path.exists(in_progress_dir) else 0
    results_count = len([f for f in os.listdir(results_dir) if f.startswith("r_")]) if os.path.exists(results_dir) else 0
    agents_count = len([f for f in os.listdir(agents_dir) if f.endswith(".json")]) if os.path.exists(agents_dir) else 0
    
    print(f"\n📊 任务统计:")
    print(f"   待执行: {queue_count}")
    print(f"   执行中: {in_progress_count}")
    print(f"   已完成: {results_count}")
    
    print(f"\n🤖 节点数量: {agents_count}")
    
    # 读取节点详情
    if os.path.exists(agents_dir):
        print(f"\n节点列表:")
        for f in os.listdir(agents_dir):
            if f.endswith(".json"):
                path = os.path.join(agents_dir, f)
                with open(path, encoding="utf-8") as fp:
                    try:
                        node = json.load(fp)
                        status = node.get("status", "unknown")
                        last_hb = node.get("last_heartbeat", "N/A")
                        print(f"   - {node.get('id', f)}: {status} (心跳: {last_hb})")
                    except:
                        pass
    
    # 审计日志
    audit_file = os.path.join(SWARM_DIR, "audit.log")
    if os.path.exists(audit_file):
        with open(audit_file, encoding="utf-8") as f:
            lines = f.readlines()
        print(f"\n📝 审计日志: {len(lines)} 条")
    
    print()


# ── 命令: 添加任务 ─────────────────────────────────────────────────

def cmd_add_task(args):
    """添加任务"""
    task = {
        "id": f"task_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "type": args.type or "general",
        "description": args.description or args.task,
        "prompt": args.prompt or args.task,
        "mode": args.mode or "spawn",
        "priority": args.priority or 1,
        "created_at": datetime.now().isoformat()
    }
    
    # 保存到队列
    queue_dir = os.path.join(SWARM_DIR, "queue")
    os.makedirs(queue_dir, exist_ok=True)
    
    task_file = os.path.join(queue_dir, f"{task['id']}.json")
    with open(task_file, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 已添加任务: {task['id']}")
    print(f"   描述: {task['description']}")
    print(f"   类型: {task['type']}")
    print(f"   模式: {task['mode']}")
    
    return 0


# ── 命令: 列出任务 ─────────────────────────────────────────────────

def cmd_list_tasks(args):
    """列出任务"""
    status_filter = args.status
    
    print("=" * 50)
    print("任务列表")
    print("=" * 50)
    
    # 待执行
    if not status_filter or status_filter == "pending":
        queue_dir = os.path.join(SWARM_DIR, "queue")
        if os.path.exists(queue_dir):
            tasks = [f for f in os.listdir(queue_dir) if f.endswith(".json")]
            print(f"\n📥 待执行 ({len(tasks)}):")
            for f in tasks[:10]:
                with open(os.path.join(queue_dir, f), encoding="utf-8") as fp:
                    task = json.load(fp)
                    print(f"   - {task.get('id')}: {task.get('description', '')[:50]}")
            if len(tasks) > 10:
                print(f"   ... 还有 {len(tasks) - 10} 个")
    
    # 执行中
    if not status_filter or status_filter == "running":
        in_progress_dir = os.path.join(SWARM_DIR, "in_progress")
        if os.path.exists(in_progress_dir):
            tasks = [f for f in os.listdir(in_progress_dir) if f.endswith(".json")]
            print(f"\n🔄 执行中 ({len(tasks)}):")
            for f in tasks[:10]:
                with open(os.path.join(in_progress_dir, f), encoding="utf-8") as fp:
                    task = json.load(fp)
                    print(f"   - {task.get('id')}: {task.get('description', '')[:50]}")
    
    # 已完成
    if not status_filter or status_filter == "done":
        results_dir = os.path.join(SWARM_DIR, "results")
        if os.path.exists(results_dir):
            tasks = [f for f in os.listdir(results_dir) if f.startswith("r_") and f.endswith(".json")]
            print(f"\n✅ 已完成 ({len(tasks)}):")
            for f in tasks[:5]:
                with open(os.path.join(results_dir, f), encoding="utf-8") as fp:
                    task = json.load(fp)
                    status = task.get("status", "unknown")
                    print(f"   - {task.get('task_id')}: {status}")
            if len(tasks) > 5:
                print(f"   ... 还有 {len(tasks) - 5} 个")
    
    print()


# ── 命令: 启动节点 ─────────────────────────────────────────────────

def cmd_start_node(args):
    """启动节点"""
    node_id = args.node_id
    
    print(f"启动节点: {node_id}")
    
    # 检查 Python
    python = sys.executable
    node_script = os.path.join(SWARM_DIR, "swarm_node.py")
    
    import subprocess
    import threading
    
    def run_node():
        subprocess.Popen(
            [python, node_script, node_id] + args.capabilities,
            cwd=SWARM_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
    
    thread = threading.Thread(target=run_node)
    thread.start()
    
    print(f"✅ 节点 {node_id} 已启动")
    print(f"   能力: {args.capabilities or ['general']}")
    
    return 0


# ── 命令: 启动调度器 ─────────────────────────────────────────────────

def cmd_start_scheduler(args):
    """启动调度器"""
    print("启动调度器...")
    
    python = sys.executable
    scheduler_script = os.path.join(SWARM_DIR, "swarm_scheduler.py")
    
    import subprocess
    import threading
    
    def run_scheduler():
        subprocess.Popen(
            [python, scheduler_script],
            cwd=SWARM_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
    
    thread = threading.Thread(target=run_scheduler)
    thread.start()
    
    print("✅ 调度器已启动")
    
    return 0


# ── 命令: 查看结果 ─────────────────────────────────────────────────

def cmd_get_result(args):
    """查看任务结果"""
    task_id = args.task_id
    
    # 查找结果文件
    results_dir = os.path.join(SWARM_DIR, "results")
    result_file = os.path.join(results_dir, f"r_{task_id}.json")
    
    if not os.path.exists(result_file):
        print(f"❌ 未找到任务结果: {task_id}")
        return 1
    
    with open(result_file, encoding="utf-8") as f:
        result = json.load(f)
    
    print("=" * 50)
    print(f"任务结果: {task_id}")
    print("=" * 50)
    
    print(f"\n状态: {result.get('status')}")
    print(f"节点: {result.get('node')}")
    print(f"完成时间: {result.get('completed_at')}")
    
    if "result" in result:
        print(f"\n结果:")
        print(result["result"])
    
    if "error" in result:
        print(f"\n错误:")
        print(result["error"])
    
    print()
    
    return 0


# ── 命令: 清理 ─────────────────────────────────────────────────────

def cmd_clean(args):
    """清理任务"""
    print("清理任务...")
    
    import shutil
    
    # 清理各目录
    dirs_to_clean = [
        ("queue", os.path.join(SWARM_DIR, "queue")),
        ("in_progress", os.path.join(SWARM_DIR, "in_progress")),
        ("results", os.path.join(SWARM_DIR, "results")),
    ]
    
    for name, path in dirs_to_clean:
        if os.path.exists(path):
            count = len(os.listdir(path))
            if args.force:
                for f in os.listdir(path):
                    try:
                        os.remove(os.path.join(path, f))
                    except:
                        pass
                print(f"   ✅ 已清理 {name}: {count} 个文件")
            else:
                print(f"   {name}: {count} 个文件 (使用 --force 清理)")
    
    # 审计日志
    if args.audit and os.path.exists(os.path.join(SWARM_DIR, "audit.log")):
        if args.force:
            os.remove(os.path.join(SWARM_DIR, "audit.log"))
            print("   ✅ 已清理审计日志")
        else:
            print("   审计日志存在 (使用 --force 清理)")
    
    return 0


# ── 命令: 测试 ─────────────────────────────────────────────────────

def cmd_test(args):
    """运行测试"""
    print("运行测试...")
    
    import subprocess
    
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v"],
        cwd=SWARM_DIR,
        capture_output=False
    )
    
    return result.returncode


# ── 主函数 ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ClawSwarm 命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # status
    subparsers.add_parser("status", help="查看集群状态")
    
    # add-task
    add_task_parser = subparsers.add_parser("add-task", help="添加任务")
    add_task_parser.add_argument("task", help="任务描述")
    add_task_parser.add_argument("--description", "-d", help="详细描述")
    add_task_parser.add_argument("--prompt", "-p", help="提示词")
    add_task_parser.add_argument("--type", "-t", help="任务类型")
    add_task_parser.add_argument("--mode", "-m", help="执行模式")
    add_task_parser.add_argument("--priority", type=int, help="优先级")
    
    # list-tasks
    list_parser = subparsers.add_parser("list-tasks", help="列出任务")
    list_parser.add_argument("--status", "-s", choices=["pending", "running", "done"], help="状态筛选")
    
    # start-node
    start_node_parser = subparsers.add_parser("start-node", help="启动节点")
    start_node_parser.add_argument("node_id", help="节点 ID")
    start_node_parser.add_argument("capabilities", nargs="*", help="节点能力")
    
    # start-scheduler
    subparsers.add_parser("start-scheduler", help="启动调度器")
    
    # result
    result_parser = subparsers.add_parser("result", help="查看任务结果")
    result_parser.add_argument("task_id", help="任务 ID")
    
    # clean
    clean_parser = subparsers.add_parser("clean", help="清理任务")
    clean_parser.add_argument("--force", "-f", action="store_true", help="强制清理")
    clean_parser.add_argument("--audit", "-a", action="store_true", help="同时清理审计日志")
    
    # test
    subparsers.add_parser("test", help="运行测试")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    # 执行命令
    commands = {
        "status": cmd_status,
        "add-task": cmd_add_task,
        "list-tasks": cmd_list_tasks,
        "start-node": cmd_start_node,
        "start-scheduler": cmd_start_scheduler,
        "result": cmd_get_result,
        "clean": cmd_clean,
        "test": cmd_test,
    }
    
    if args.command in commands:
        return commands[args.command](args)
    else:
        print(f"未知命令: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
