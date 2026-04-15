"""
ClawSwarm Result Pipeline - Result aggregation pipeline

Reads results from swarm_data/results/, applies post-processing,
and produces aggregated output.

Pipeline stages:
  1. Collect: Read result files matching labels
  2. Filter: Remove failed/timeout results (configurable)
  3. Transform: Normalize output format
  4. Aggregate: Merge into unified output
  5. Export: Write final result + optional summary
"""

import json
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional


# ── Paths ─────────────────────────────────────────────────────────────

from paths import RESULTS_DIR, PIPELINE_DIR, ensure_dirs


# ── Pipeline ─────────────────────────────────────────────────────────

class ResultPipeline:
    """Multi-stage result aggregation pipeline."""

    def __init__(self, pipeline_id: str = None):
        self.pipeline_id = pipeline_id or f"pipe_{int(time.time())}"
        self._results: Dict[str, dict] = {}
        self._metadata = {
            "id": self.pipeline_id,
            "created_at": datetime.now().isoformat(),
            "stages": [],
        }

    def collect(self, label: str, timeout: int = 60) -> bool:
        """Stage 1: Collect result file matching label."""
        start = time.time()
        while time.time() - start < timeout:
            for rf in sorted(Path(RESULTS_DIR).glob(f"r_*{label}*.json"),
                            key=lambda p: p.stat().st_mtime):
                try:
                    with open(rf, encoding="utf-8") as f:
                        data = json.load(f)
                    self._results[label] = {
                        "data": data,
                        "file": str(rf),
                        "collected_at": datetime.now().isoformat(),
                    }
                    self._metadata["stages"].append({
                        "stage": "collect",
                        "label": label,
                        "file": str(rf),
                        "status": "ok",
                    })
                    return True
                except Exception as e:
                    self._metadata["stages"].append({
                        "stage": "collect",
                        "label": label,
                        "error": str(e),
                        "status": "error",
                    })
                    return False
            time.sleep(1)

        self._metadata["stages"].append({
            "stage": "collect",
            "label": label,
            "status": "timeout",
        })
        return False

    def collect_batch(self, labels: List[str], timeout: int = 60) -> Dict[str, bool]:
        """Collect multiple results. Returns {label: success}."""
        results = {}
        for label in labels:
            results[label] = self.collect(label, timeout=max(1, timeout // len(labels)))
        return results

    def filter_failed(self, exclude_status: List[str] = None) -> int:
        """Stage 2: Filter out failed results."""
        exclude = exclude_status or ["failed", "timeout", "error"]
        before = len(self._results)
        self._results = {
            k: v for k, v in self._results.items()
            if v["data"].get("status") not in exclude
        }
        removed = before - len(self._results)
        self._metadata["stages"].append({
            "stage": "filter",
            "excluded": exclude,
            "removed": removed,
            "remaining": len(self._results),
        })
        return removed

    def transform(self, key: str = "output") -> Dict[str, str]:
        """Stage 3: Extract and normalize outputs."""
        outputs = {}
        for label, entry in self._results.items():
            data = entry["data"]
            # Try multiple output keys
            output = (
                data.get(key)
                or data.get("result", {}).get("output")
                or data.get("text", "")
                or str(data)
            )
            outputs[label] = output

        self._metadata["stages"].append({
            "stage": "transform",
            "key": key,
            "count": len(outputs),
        })
        return outputs

    def aggregate(self, outputs: Dict[str, str], separator: str = "\n\n---\n\n") -> str:
        """Stage 4: Merge outputs into single string."""
        parts = []
        for label, output in outputs.items():
            parts.append(f"## {label}\n\n{output}")

        merged = separator.join(parts)
        self._metadata["stages"].append({
            "stage": "aggregate",
            "labels": list(outputs.keys()),
            "total_chars": len(merged),
        })
        return merged

    def export(self, content: str, filename: str = None) -> str:
        """Stage 5: Write aggregated result to file."""
        ensure_dirs()
        os.makedirs(PIPELINE_DIR, exist_ok=True)

        filename = filename or f"{self.pipeline_id}.json"
        file_path = os.path.join(PIPELINE_DIR, filename)

        output = {
            "pipeline_id": self.pipeline_id,
            "exported_at": datetime.now().isoformat(),
            "labels": list(self._results.keys()),
            "metadata": self._metadata,
            "content": content,
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        return file_path

    def run(self, labels: List[str], timeout: int = 60,
            exclude_status: List[str] = None) -> str:
        """
        Run the full pipeline: collect -> filter -> transform -> aggregate -> export.

        Returns the aggregated content string.
        """
        # Collect
        self.collect_batch(labels, timeout)

        # Filter
        self.filter_failed(exclude_status)

        # Transform
        outputs = self.transform()

        # Aggregate
        content = self.aggregate(outputs)

        # Export
        file_path = self.export(content)
        self._metadata["result_file"] = file_path

        return content

    def summary(self) -> dict:
        """Get pipeline execution summary."""
        return {
            "pipeline_id": self.pipeline_id,
            "collected": len(self._results),
            "labels": list(self._results.keys()),
            "stages_completed": len(self._metadata["stages"]),
            "stages": self._metadata["stages"],
        }


# ── Convenience ──────────────────────────────────────────────────────

def quick_aggregate(labels: List[str], timeout: int = 60) -> str:
    """One-shot aggregate: run full pipeline and return content."""
    pipeline = ResultPipeline()
    return pipeline.run(labels, timeout)
