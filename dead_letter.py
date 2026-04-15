"""
ClawSwarm Dead Letter Queue (DLQ) - Phase 2

Handles tasks that failed, timed out, or exceeded max retries.
Tasks enter DLQ when:
  1. executor marks task as failed AND retry_count >= max_retries
  2. scheduler detects task timeout (running too long)
  3. manual intervention moves task to DLQ

DLQ tasks can be:
  - Inspected (list/query)
  - Retried (move back to queue)
  - Purged (delete permanently)
"""

import json
import time
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────

from paths import BASE_DIR, QUEUE_DIR, IN_PROGRESS_DIR, RESULTS_DIR, DEAD_LETTER_DIR, ensure_dirs


# ── Dead Letter Entry ────────────────────────────────────────────────

class DeadLetterReason:
    """Reasons a task enters DLQ"""
    MAX_RETRIES = "max_retries_exceeded"
    TIMEOUT = "execution_timeout"
    NODE_FAILURE = "node_failure"
    MANUAL = "manual_move"
    UNKNOWN = "unknown_error"


def enqueue(task_data: dict, reason: str, error_detail: str = "") -> str:
    """
    Move a task to the dead letter queue.

    Args:
        task_data: Original task dict (from queue/in_progress)
        reason: One of DeadLetterReason constants
        error_detail: Human-readable error description

    Returns:
        DLQ entry ID (dlq_<timestamp>)
    """
    ensure_dirs()
    entry_id = f"dlq_{task_data.get('id', 'unknown')}_{int(time.time() * 1000)}"
    entry = {
        "id": entry_id,
        "original_task_id": task_data.get("id", "unknown"),
        "reason": reason,
        "error_detail": error_detail,
        "retry_count": task_data.get("retry_count", 0),
        "max_retries": task_data.get("max_retries", 3),
        "enqueued_at": datetime.now().isoformat(),
        "original_task": task_data,
    }

    file_path = os.path.join(DEAD_LETTER_DIR, f"{entry_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)

    return entry_id


def list_entries(reason: str = None, limit: int = 50) -> List[dict]:
    """
    List dead letter entries.

    Args:
        reason: Filter by reason (optional)
        limit: Max entries to return
    """
    ensure_dirs()
    entries = []
    for f in sorted(Path(DEAD_LETTER_DIR).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(f, encoding="utf-8") as fp:
                entry = json.load(fp)
            if reason and entry.get("reason") != reason:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
        except Exception:
            pass
    return entries


def retry(entry_id: str) -> Optional[str]:
    """
    Retry a DLQ entry by moving it back to the queue.

    Returns:
        New task ID if successful, None if entry not found
    """
    ensure_dirs()
    file_path = os.path.join(DEAD_LETTER_DIR, f"{entry_id}.json")
    if not os.path.exists(file_path):
        return None

    with open(file_path, encoding="utf-8") as f:
        entry = json.load(f)

    original = entry.get("original_task", {})
    # Reset state for retry
    original["retry_count"] = original.get("retry_count", 0) + 1
    original["status"] = "pending"
    original["dlq_reason"] = entry.get("reason")

    task_id = f"retry_{int(time.time())}"
    original["id"] = task_id

    task_file = os.path.join(QUEUE_DIR, f"{task_id}.json")
    with open(task_file, "w", encoding="utf-8") as f:
        json.dump(original, f, ensure_ascii=False, indent=2)

    # Remove from DLQ
    os.remove(file_path)

    return task_id


def purge(entry_id: str = None, reason: str = None) -> int:
    """
    Remove entries from DLQ.

    Args:
        entry_id: Specific entry to purge (optional)
        reason: Purge all entries with this reason (optional)
        If both None, purge all entries.

    Returns:
        Number of entries purged
    """
    ensure_dirs()
    count = 0
    for f in Path(DEAD_LETTER_DIR).glob("*.json"):
        try:
            if entry_id:
                if f.stem == entry_id:
                    os.remove(f)
                    count += 1
            elif reason:
                with open(f, encoding="utf-8") as fp:
                    entry = json.load(fp)
                if entry.get("reason") == reason:
                    os.remove(f)
                    count += 1
            else:
                os.remove(f)
                count += 1
        except Exception:
            pass
    return count


def stats() -> dict:
    """Get DLQ statistics."""
    ensure_dirs()
    entries = list(Path(DEAD_LETTER_DIR).glob("*.json"))
    reasons = {}
    for f in entries:
        try:
            with open(f, encoding="utf-8") as fp:
                entry = json.load(fp)
            r = entry.get("reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1
        except Exception:
            pass

    return {
        "total": len(entries),
        "by_reason": reasons,
        "dir": DEAD_LETTER_DIR,
    }
