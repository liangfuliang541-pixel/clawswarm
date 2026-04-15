#!/usr/bin/env python3
"""ClawSwarm Demo — 统帅千军万马实战演示

用法:
    python demo.py                    # 交互式菜单
    python demo.py --scenario ai-news # 直接运行预设场景
    python demo.py --custom "你的任务" # 自定义任务
"""

import sys, os, time, json, argparse
from pathlib import Path

# ── setup ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("OPENCLAW_WORKSPACE", str(BASE_DIR))

from orchestrate import orchestrate

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except:
    pass

# ── preset scenarios ──────────────────────────────────────────────────────────
SCENARIOS = {
    "ai-news": {
        "emoji":  "🔬",
        "title":  "AI 最新动态简报",
        "prompt": "研究 2026 年 AI 最新动态，生成一份简报",
        "timeout": 300,
    },
    "code-review": {
        "emoji":  "🔍",
        "title":  "代码审查 + 优化建议",
        "prompt": "对项目中 executor.py 进行代码审查，列出问题和优化建议",
        "timeout": 300,
    },
    "market-scan": {
        "emoji":  "📊",
        "title":  "竞品调研 + 分析报告",
        "prompt": "调研 CrewAI / LangGraph / AutoGen 最新动态，生成对比分析报告",
        "timeout": 300,
    },
    "tech-deep": {
        "emoji":  "🧠",
        "title":  "技术深度解析 + 落地建议",
        "prompt": "深度解析 MCP 协议架构，评估落地可行性并给出实施建议",
        "timeout": 300,
    },
}

# ── banner ───────────────────────────────────────────────────────────────────
BANNER = r"""
  ╔══════════════════════════════════════════════════════╗
  ║                                                      ║
  ║     🦞  ClawSwarm  Demo  —  统帅千军万马            ║
  ║                                                      ║
  ║     一只龙虾，统帅千军万马                           ║
  ║     One prompt commands the swarm                    ║
  ║                                                      ║
  ╚══════════════════════════════════════════════════════╝
"""

MENU = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  预设场景
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [1] 🔬  AI 最新动态简报
      研究 2026 年 AI 最新动态，生成一份简报

  [2] 🔍  代码审查 + 优化建议
      对 executor.py 进行代码审查，列出问题

  [3] 📊  竞品调研 + 分析报告
      CrewAI / LangGraph / AutoGen 对比分析

  [4] 🧠  技术深度解析 + 落地建议
      深度解析 MCP 协议架构，给出实施建议

  [0] ✏️   自定义任务
      输入任意自然语言任务描述

  [Q]  退出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

SEP = "─" * 60

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def print_banner():
    print(BANNER)

def run_scenario(key: str, timeout: int = 300) -> dict:
    scenario = SCENARIOS[key]
    print()
    print(f"  {scenario['emoji']}  启动场景: {scenario['title']}")
    print(SEP)
    print(f"  📝 任务: {scenario['prompt']}")
    print(SEP)

    start = time.time()
    result = orchestrate(scenario["prompt"], timeout=timeout)
    elapsed = time.time() - start

    print(SEP)

    # sub-tasks results
    results = result.get("results", {})
    subs    = result.get("sub_tasks", [])
    ok      = sum(1 for r in results.values() if r and r.get("status") == "success")
    status_icon = "✅" if result.get("success") else "⚠️"
    print(f"\n  {status_icon} 完成（{elapsed:.1f}s，{ok}/{len(results)} 子任务成功）")

    # print each sub-task result
    for s in subs:
        sid  = s["id"]
        r    = results.get(sid, {})
        stat = r.get("status", "unknown")
        icon = "✅" if stat == "success" else ("⏳" if stat == "timeout" else "❌")
        output = r.get("output", r.get("result", ""))
        print(f"\n  [{icon}] {s['id']} — {s['description'][:50]}")
        if output:
            snippet = str(output).strip()[:600]
            print(f"  {snippet}")
            if len(str(output)) > 600:
                print(f"  ... (+{len(str(output))-600} chars)")

    # final aggregated output
    final = result.get("final_output", "")
    if final:
        print(f"\n  📦 聚合报告:")
        print(SEP)
        print(final[:2000])
        if len(final) > 2000:
            print(f"  ... (+{len(final)-2000} chars)")

    return result

def interactive():
    while True:
        clear()
        print_banner()
        print(MENU)
        choice = input("\n  请选择 [1-4, 0, Q]: ").strip()

        if choice.lower() == "q":
            print("\n  👋 再见！\n")
            break

        if choice == "1":
            run_scenario("ai-news")
        elif choice == "2":
            run_scenario("code-review")
        elif choice == "3":
            run_scenario("market-scan")
        elif choice == "4":
            run_scenario("tech-deep")
        elif choice == "0":
            custom = input("\n  请输入任务描述: ").strip()
            if custom:
                run_scenario("custom", timeout=300)
        else:
            print("\n  ⚠️  无效选择")
            time.sleep(1)
            continue

        input("\n  ↵ 按回车继续...")

def main():
    parser = argparse.ArgumentParser(description="ClawSwarm Demo — 统帅千军万马实战演示")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), help="直接运行预设场景")
    parser.add_argument("--custom", type=str, help="自定义任务描述")
    parser.add_argument("--timeout", type=int, default=300, help="超时秒数（默认300）")
    args = parser.parse_args()

    if args.scenario:
        print_banner()
        run_scenario(args.scenario, timeout=args.timeout)
    elif args.custom:
        print_banner()
        print(f"  🚀  自定义任务")
        print(SEP)
        print(f"  📝 {args.custom}")
        print(SEP)
        start = time.time()
        result = orchestrate(args.custom, timeout=args.timeout)
        elapsed = time.time() - start
        print(SEP)
        ok = sum(1 for r in result.get("results", {}).values() if r and r.get("status") == "success")
        print(f"\n  ✅ 完成（{elapsed:.1f}s，{ok}/{len(result.get('results',{}))} 子任务成功）")
        final = result.get("final_output", "")
        if final:
            print(f"\n  📦 聚合报告:\n{SEP}")
            print(final[:1500])
    else:
        interactive()

if __name__ == "__main__":
    main()
