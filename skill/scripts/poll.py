#!/usr/bin/env python3
"""
ClawSwarm Poll Script — 轮询等待结果文件

用法:
    python poll.py --label research_1 [--timeout 120] [--poll-interval 5]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

RESULTS_DIR = Path(os.environ.get("CLAWSWARM_RESULTS_DIR", "results"))
DEFAULT_POLL_INTERVAL = 5


def find_result_file(label: str) -> Optional[Path]:
    """查找匹配 label 的最新结果文件"""
    if not RESULTS_DIR.exists():
        return None
    candidates = list(RESULTS_DIR.glob(f"*{label}*.json"))
    if not candidates:
        candidates = list(RESULTS_DIR.glob(f"*/*{label}*.json"))
    if not candidates:
        return None
    # 按修改时间排序，返回最新的
    return max(candidates, key=lambda p: p.stat().st_mtime)


def poll_for_result(label: str, timeout: float = 300, poll_interval: float = DEFAULT_POLL_INTERVAL) -> dict:
    """轮询等待结果文件"""
    start = time.time()

    while time.time() - start < timeout:
        path = find_result_file(label)
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    return {
                        "status": "found",
                        "label": label,
                        "result_file": str(path),
                        "elapsed_seconds": round(time.time() - start, 1),
                        "result": json.load(f),
                    }
            except Exception as e:
                return {
                    "status": "error",
                    "label": label,
                    "output": f"读取结果文件失败: {e}",
                }

        time.sleep(poll_interval)

    return {
        "status": "timeout",
        "label": label,
        "timeout_seconds": timeout,
        "elapsed_seconds": round(time.time() - start, 1),
        "searched_dir": str(RESULTS_DIR),
    }


def main():
    parser = argparse.ArgumentParser(description="ClawSwarm Result Poller")
    parser.add_argument("--label", required=True, help="要等待的结果标签")
    parser.add_argument("--timeout", type=float, default=300, help="超时秒数 (默认: 300)")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL, help=f"轮询间隔秒数 (默认: {DEFAULT_POLL_INTERVAL})")
    parser.add_argument("--results-dir", default=None, help=f"结果目录 (默认: {RESULTS_DIR})")

    args = parser.parse_args()

    global RESULTS_DIR
    if args.results_dir:
        RESULTS_DIR = Path(args.results_dir)

    result = poll_for_result(
        label=args.label,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
