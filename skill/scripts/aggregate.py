#!/usr/bin/env python3
"""
ClawSwarm Aggregate Script — 聚合多个结果

用法:
    python aggregate.py --labels research,write,code --output final.json

输出格式:
{
  "status": "aggregated",
  "results": {
    "research": { ... result from research agent ... },
    "write": { ... result from write agent ... },
  },
  "final_output": "综合多个结果的最终摘要"
}
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(os.environ.get("CLAWSWARM_RESULTS_DIR", "results"))


def find_result(label: str) -> tuple[str, Any] | None:
    """查找匹配 label 的最新结果文件"""
    if not RESULTS_DIR.exists():
        return None
    candidates = list(RESULTS_DIR.glob(f"*{label}*.json"))
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    with open(latest, encoding="utf-8") as f:
        return str(latest), json.load(f)


def aggregate_results(labels: list[str]) -> dict:
    """聚合所有 label 的结果"""
    results: dict[str, Any] = {}
    errors: list[str] = []

    for label in labels:
        found = find_result(label)
        if found:
            path, data = found
            results[label] = {
                "status": data.get("status", "unknown"),
                "output": data.get("output", ""),
                "details": data.get("details", {}),
                "source_file": path,
            }
        else:
            results[label] = {
                "status": "not_found",
                "output": f"未找到 label={label} 的结果",
            }
            errors.append(label)

    # 生成综合摘要
    all_outputs = []
    for label, data in results.items():
        status = data.get("status", "unknown")
        output = data.get("output", "")
        all_outputs.append(f"[{label}] {status}: {output}")

    summary = "\n".join(all_outputs) if all_outputs else "无结果"

    overall_status = "success" if not errors else "partial" if results else "error"

    return {
        "status": overall_status,
        "aggregated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "labels_requested": labels,
        "labels_found": list(results.keys()),
        "labels_missing": errors,
        "results": results,
        "final_summary": summary,
    }


def main():
    parser = argparse.ArgumentParser(description="ClawSwarm Result Aggregator")
    parser.add_argument("--labels", required=True, help="逗号分隔的 label 列表")
    parser.add_argument("--output", required=True, help="最终输出文件路径")
    parser.add_argument("--results-dir", default=None, help=f"结果目录 (默认: {RESULTS_DIR})")

    args = parser.parse_args()

    global RESULTS_DIR
    if args.results_dir:
        RESULTS_DIR = Path(args.results_dir)

    labels = [l.strip() for l in args.labels.split(",") if l.strip()]
    result = aggregate_results(labels)

    # 写入输出文件
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
