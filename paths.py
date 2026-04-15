"""
ClawSwarm Paths - 共享路径与配置
所有模块从这里获取 BASE_DIR 和子目录路径，杜绝硬编码。

优先级：
  1. 环境变量 CLAWSWARM_HOME
  2. 当前工作目录下的 swarm_config.json → base_dir 字段
  3. 默认 ./swarm_data（项目根目录下，可 gitignore）
"""

import os
import json
from pathlib import Path

# ── BASE_DIR 解析 ──────────────────────────────────────────────────────

def _resolve_base_dir() -> str:
    """解析 CLAWSWARM_HOME 环境变量或配置文件"""
    # 1. 环境变量
    env = os.environ.get("CLAWSWARM_HOME")
    if env:
        return os.path.abspath(env)

    # 2. 配置文件（向上搜索 swarm_config.json）
    here = Path(__file__).resolve().parent
    for candidate in [here] + list(here.parents)[:3]:
        cfg = candidate / "swarm_config.json"
        if cfg.exists():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                base = data.get("base_dir")
                if base:
                    return str((candidate / base).resolve())
            except Exception:
                pass

    # 3. 默认：项目根目录下 swarm_data/
    return str(here / "swarm_data")


BASE_DIR = _resolve_base_dir()

# ── 子目录 ─────────────────────────────────────────────────────────────

QUEUE_DIR       = os.path.join(BASE_DIR, "queue")
IN_PROGRESS_DIR = os.path.join(BASE_DIR, "in_progress")
RESULTS_DIR     = os.path.join(BASE_DIR, "results")
AGENTS_DIR      = os.path.join(BASE_DIR, "agents")
LOGS_DIR        = os.path.join(BASE_DIR, "logs")
AUDIT_LOG_FILE  = os.path.join(BASE_DIR, "audit.log")


def ensure_dirs():
    """确保所有必要目录存在"""
    for d in [QUEUE_DIR, IN_PROGRESS_DIR, RESULTS_DIR, AGENTS_DIR, LOGS_DIR]:
        os.makedirs(d, exist_ok=True)


# ── 能力映射 ─────────────────────────────────────────────────────────────

CAPABILITY_MAP = {
    "research":  ["search", "analyze", "report"],
    "code":      ["code", "write"],
    "write":     ["write"],
    "read":      ["read"],
    "fetch":     ["search", "web_fetch"],
    "report":    ["report", "write"],
    "analyze":   ["analyze"],
    "general":   ["*"],
}


def required_capabilities(task_type: str) -> list:
    """获取任务类型所需的能力列表"""
    return CAPABILITY_MAP.get(task_type, CAPABILITY_MAP["general"])


def can_node_handle(task_type: str, node_capabilities: list) -> bool:
    """判断节点是否具备处理某类型任务的能力"""
    required = required_capabilities(task_type)
    if required == ["*"]:
        return True
    return all(cap in node_capabilities for cap in required)


def find_best_node(task_type: str, online_nodes: list) -> dict | None:
    """
    从在线节点中选出最适合执行该类型任务的节点。
    策略：能力匹配 + 负载最低优先（completed_tasks 最少）。
    """
    candidates = [
        n for n in online_nodes
        if can_node_handle(task_type, n.get("capabilities", []))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda n: n.get("completed_tasks", 0))


# ── 自动初始化 ─────────────────────────────────────────────────────────
ensure_dirs()
