"""
ClawSwarm 鍛戒护琛屽伐鍏?

鎻愪緵渚挎嵎鐨?CLI 鍛戒护鏉ョ鐞嗛泦缇?

鐢ㄦ硶:
    python cli.py status
    python cli.py add-task "浠诲姟鎻忚堪"
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

from paths import BASE_DIR, QUEUE_DIR, IN_PROGRESS_DIR, RESULTS_DIR, AGENTS_DIR

# 鈹€鈹€ 鍛戒护: 鐘舵€?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def cmd_status(args):
    """鏌ョ湅闆嗙兢鐘舵€?""
    print("=" * 50)
    print("ClawSwarm 闆嗙兢鐘舵€?)
    print("=" * 50)
    
    # 璇诲彇闃熷垪
    queue_dir = os.path.join(BASE_DIR, "queue")
    in_progress_dir = os.path.join(BASE_DIR, "in_progress")
    results_dir = os.path.join(BASE_DIR, "results")
    agents_dir = os.path.join(BASE_DIR, "agents")
    
    queue_count = len([f for f in os.listdir(queue_dir) if f.endswith(".json")]) if os.path.exists(queue_dir) else 0
    in_progress_count = len([f for f in os.listdir(in_progress_dir) if f.endswith(".json")]) if os.path.exists(in_progress_dir) else 0
    results_count = len([f for f in os.listdir(results_dir) if f.startswith("r_")]) if os.path.exists(results_dir) else 0
    agents_count = len([f for f in os.listdir(agents_dir) if f.endswith(".json")]) if os.path.exists(agents_dir) else 0
    
    print(f"\n馃搳 浠诲姟缁熻:")
    print(f"   寰呮墽琛? {queue_count}")
    print(f"   鎵ц涓? {in_progress_count}")
    print(f"   宸插畬鎴? {results_count}")
    
    print(f"\n馃 鑺傜偣鏁伴噺: {agents_count}")
    
    # 璇诲彇鑺傜偣璇︽儏
    if os.path.exists(agents_dir):
        print(f"\n鑺傜偣鍒楄〃:")
        for f in os.listdir(agents_dir):
            if f.endswith(".json"):
                path = os.path.join(agents_dir, f)
                with open(path, encoding="utf-8") as fp:
                    try:
                        node = json.load(fp)
                        status = node.get("status", "unknown")
                        last_hb = node.get("last_heartbeat", "N/A")
                        print(f"   - {node.get('id', f)}: {status} (蹇冭烦: {last_hb})")
                    except:
                        pass
    
    # 瀹¤鏃ュ織
    audit_file = os.path.join(BASE_DIR, "audit.log")
    if os.path.exists(audit_file):
        with open(audit_file, encoding="utf-8") as f:
            lines = f.readlines()
        print(f"\n馃摑 瀹¤鏃ュ織: {len(lines)} 鏉?)
    
    print()


# 鈹€鈹€ 鍛戒护: 娣诲姞浠诲姟 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def cmd_add_task(args):
    """娣诲姞浠诲姟"""
    task = {
        "id": f"task_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "type": args.type or "general",
        "description": args.description or args.task,
        "prompt": args.prompt or args.task,
        "mode": args.mode or "spawn",
        "priority": args.priority or 1,
        "created_at": datetime.now().isoformat()
    }
    
    # 淇濆瓨鍒伴槦鍒?
    queue_dir = os.path.join(BASE_DIR, "queue")
    os.makedirs(queue_dir, exist_ok=True)
    
    task_file = os.path.join(queue_dir, f"{task['id']}.json")
    with open(task_file, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    
    print(f"鉁?宸叉坊鍔犱换鍔? {task['id']}")
    print(f"   鎻忚堪: {task['description']}")
    print(f"   绫诲瀷: {task['type']}")
    print(f"   妯″紡: {task['mode']}")
    
    return 0


# 鈹€鈹€ 鍛戒护: 鍒楀嚭浠诲姟 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def cmd_list_tasks(args):
    """鍒楀嚭浠诲姟"""
    status_filter = args.status
    
    print("=" * 50)
    print("浠诲姟鍒楄〃")
    print("=" * 50)
    
    # 寰呮墽琛?
    if not status_filter or status_filter == "pending":
        queue_dir = os.path.join(BASE_DIR, "queue")
        if os.path.exists(queue_dir):
            tasks = [f for f in os.listdir(queue_dir) if f.endswith(".json")]
            print(f"\n馃摜 寰呮墽琛?({len(tasks)}):")
            for f in tasks[:10]:
                with open(os.path.join(queue_dir, f), encoding="utf-8") as fp:
                    task = json.load(fp)
                    print(f"   - {task.get('id')}: {task.get('description', '')[:50]}")
            if len(tasks) > 10:
                print(f"   ... 杩樻湁 {len(tasks) - 10} 涓?)
    
    # 鎵ц涓?
    if not status_filter or status_filter == "running":
        in_progress_dir = os.path.join(BASE_DIR, "in_progress")
        if os.path.exists(in_progress_dir):
            tasks = [f for f in os.listdir(in_progress_dir) if f.endswith(".json")]
            print(f"\n馃攧 鎵ц涓?({len(tasks)}):")
            for f in tasks[:10]:
                with open(os.path.join(in_progress_dir, f), encoding="utf-8") as fp:
                    task = json.load(fp)
                    print(f"   - {task.get('id')}: {task.get('description', '')[:50]}")
    
    # 宸插畬鎴?
    if not status_filter or status_filter == "done":
        results_dir = os.path.join(BASE_DIR, "results")
        if os.path.exists(results_dir):
            tasks = [f for f in os.listdir(results_dir) if f.startswith("r_") and f.endswith(".json")]
            print(f"\n鉁?宸插畬鎴?({len(tasks)}):")
            for f in tasks[:5]:
                with open(os.path.join(results_dir, f), encoding="utf-8") as fp:
                    task = json.load(fp)
                    status = task.get("status", "unknown")
                    print(f"   - {task.get('task_id')}: {status}")
            if len(tasks) > 5:
                print(f"   ... 杩樻湁 {len(tasks) - 5} 涓?)
    
    print()


# 鈹€鈹€ 鍛戒护: 鍚姩鑺傜偣 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def cmd_start_node(args):
    """鍚姩鑺傜偣"""
    node_id = args.node_id
    
    print(f"鍚姩鑺傜偣: {node_id}")
    
    # 妫€鏌?Python
    python = sys.executable
    node_script = os.path.join(BASE_DIR, "swarm_node.py")
    
    import subprocess
    import threading
    
    def run_node():
        subprocess.Popen(
            [python, node_script, node_id] + args.capabilities,
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
    
    thread = threading.Thread(target=run_node)
    thread.start()
    
    print(f"鉁?鑺傜偣 {node_id} 宸插惎鍔?)
    print(f"   鑳藉姏: {args.capabilities or ['general']}")
    
    return 0


# 鈹€鈹€ 鍛戒护: 鍚姩璋冨害鍣?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def cmd_start_scheduler(args):
    """鍚姩璋冨害鍣?""
    print("鍚姩璋冨害鍣?..")
    
    python = sys.executable
    scheduler_script = os.path.join(BASE_DIR, "swarm_scheduler.py")
    
    import subprocess
    import threading
    
    def run_scheduler():
        subprocess.Popen(
            [python, scheduler_script],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
    
    thread = threading.Thread(target=run_scheduler)
    thread.start()
    
    print("鉁?璋冨害鍣ㄥ凡鍚姩")
    
    return 0


# 鈹€鈹€ 鍛戒护: 鏌ョ湅缁撴灉 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def cmd_get_result(args):
    """鏌ョ湅浠诲姟缁撴灉"""
    task_id = args.task_id
    
    # 鏌ユ壘缁撴灉鏂囦欢
    results_dir = os.path.join(BASE_DIR, "results")
    result_file = os.path.join(results_dir, f"r_{task_id}.json")
    
    if not os.path.exists(result_file):
        print(f"鉂?鏈壘鍒颁换鍔＄粨鏋? {task_id}")
        return 1
    
    with open(result_file, encoding="utf-8") as f:
        result = json.load(f)
    
    print("=" * 50)
    print(f"浠诲姟缁撴灉: {task_id}")
    print("=" * 50)
    
    print(f"\n鐘舵€? {result.get('status')}")
    print(f"鑺傜偣: {result.get('node')}")
    print(f"瀹屾垚鏃堕棿: {result.get('completed_at')}")
    
    if "result" in result:
        print(f"\n缁撴灉:")
        print(result["result"])
    
    if "error" in result:
        print(f"\n閿欒:")
        print(result["error"])
    
    print()
    
    return 0


# 鈹€鈹€ 鍛戒护: 娓呯悊 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def cmd_clean(args):
    """娓呯悊浠诲姟"""
    print("娓呯悊浠诲姟...")
    
    import shutil
    
    # 娓呯悊鍚勭洰褰?
    dirs_to_clean = [
        ("queue", os.path.join(BASE_DIR, "queue")),
        ("in_progress", os.path.join(BASE_DIR, "in_progress")),
        ("results", os.path.join(BASE_DIR, "results")),
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
                print(f"   鉁?宸叉竻鐞?{name}: {count} 涓枃浠?)
            else:
                print(f"   {name}: {count} 涓枃浠?(浣跨敤 --force 娓呯悊)")
    
    # 瀹¤鏃ュ織
    if args.audit and os.path.exists(os.path.join(BASE_DIR, "audit.log")):
        if args.force:
            os.remove(os.path.join(BASE_DIR, "audit.log"))
            print("   鉁?宸叉竻鐞嗗璁℃棩蹇?)
        else:
            print("   瀹¤鏃ュ織瀛樺湪 (浣跨敤 --force 娓呯悊)")
    
    return 0


# 鈹€鈹€ 鍛戒护: 娴嬭瘯 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def cmd_test(args):
    """杩愯娴嬭瘯"""
    print("杩愯娴嬭瘯...")
    
    import subprocess
    
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v"],
        cwd=BASE_DIR,
        capture_output=False
    )
    
    return result.returncode


# 鈹€鈹€ 涓诲嚱鏁?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def main():
    parser = argparse.ArgumentParser(
        description="ClawSwarm 鍛戒护琛屽伐鍏?,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="鍙敤鍛戒护")
    
    # status
    subparsers.add_parser("status", help="鏌ョ湅闆嗙兢鐘舵€?)
    
    # add-task
    add_task_parser = subparsers.add_parser("add-task", help="娣诲姞浠诲姟")
    add_task_parser.add_argument("task", help="浠诲姟鎻忚堪")
    add_task_parser.add_argument("--description", "-d", help="璇︾粏鎻忚堪")
    add_task_parser.add_argument("--prompt", "-p", help="鎻愮ず璇?)
    add_task_parser.add_argument("--type", "-t", help="浠诲姟绫诲瀷")
    add_task_parser.add_argument("--mode", "-m", help="鎵ц妯″紡")
    add_task_parser.add_argument("--priority", type=int, help="浼樺厛绾?)
    
    # list-tasks
    list_parser = subparsers.add_parser("list-tasks", help="鍒楀嚭浠诲姟")
    list_parser.add_argument("--status", "-s", choices=["pending", "running", "done"], help="鐘舵€佺瓫閫?)
    
    # start-node
    start_node_parser = subparsers.add_parser("start-node", help="鍚姩鑺傜偣")
    start_node_parser.add_argument("node_id", help="鑺傜偣 ID")
    start_node_parser.add_argument("capabilities", nargs="*", help="鑺傜偣鑳藉姏")
    
    # start-scheduler
    subparsers.add_parser("start-scheduler", help="鍚姩璋冨害鍣?)
    
    # result
    result_parser = subparsers.add_parser("result", help="鏌ョ湅浠诲姟缁撴灉")
    result_parser.add_argument("task_id", help="浠诲姟 ID")
    
    # clean
    clean_parser = subparsers.add_parser("clean", help="娓呯悊浠诲姟")
    clean_parser.add_argument("--force", "-f", action="store_true", help="寮哄埗娓呯悊")
    clean_parser.add_argument("--audit", "-a", action="store_true", help="鍚屾椂娓呯悊瀹¤鏃ュ織")
    
    # test
    subparsers.add_parser("test", help="杩愯娴嬭瘯")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    # 鎵ц鍛戒护
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
        print(f"鏈煡鍛戒护: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

