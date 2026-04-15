"""
ClawSwarm - Agent 角色系统

借鉴 CrewAI 的 Role-Based Agent 理念：
- 每个 Agent 有 role（角色）、goal（目标）、backstory（背景故事）
- 角色定义决定工具集和行为模式
- 支持工具白名单 + 提示词模板

核心类:
    Role         — 角色定义（role/goal/backstory/tools）
    AgentProfile — Agent 实例配置
    RoleRegistry — 全剧角色注册表

用法:
    registry = RoleRegistry()
    registry.register(RESEARCHER)
    researcher = registry.create_agent("claw_researcher", model="gpt-4o")
"""

import json, os, time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from paths import BASE_DIR

from models import TaskStatus


# ── 预定义角色库 ─────────────────────────────────────────────────────────────

RESEARCHER = {
    "name":        "Researcher",
    "role":        "高级研究员",
    "goal":        "从互联网上搜集、筛选和整理高质量信息",
    "backstory":   (
        "你是一名经验丰富的市场研究员，擅长从海量信息中提炼关键洞察。"
        "你严谨、客观，注重数据的时效性和来源权威性。"
        "你会交叉验证多个来源，确保信息的准确性。"
    ),
    "tools":       ["web_search", "web_fetch", "file_read"],
    "default_model": "gpt-4o",
    "temperature":  0.3,
}

WRITER = {
    "name":        "Writer",
    "role":        "专业内容创作者",
    "goal":        "将研究素材转化为清晰、专业、有价值的内容",
    "backstory":   (
        "你是一名资深的内容创作者，曾在顶级媒体工作多年。"
        "你擅长将复杂的技术概念用通俗易懂的语言表达。"
        "你注重逻辑结构、可读性，并根据受众调整文风。"
    ),
    "tools":       ["file_write", "file_read"],
    "default_model": "gpt-4o",
    "temperature":  0.7,
}

CODE_AGENT = {
    "name":        "CodeAgent",
    "role":        "软件工程师",
    "goal":        "编写、审查和调试高质量代码",
    "backstory":   (
        "你是一名全栈工程师，精通 Python、JavaScript 和系统设计。"
        "你追求代码的可读性、可维护性和性能。"
        "你习惯写测试、写文档，遵循最佳实践。"
    ),
    "tools":       ["bash", "file_read", "file_write", "code_execute"],
    "default_model": "gpt-4o",
    "temperature":  0.2,
}

ANALYZER = {
    "name":        "Analyzer",
    "role":        "数据分析师",
    "goal":        "从数据中发现模式、趋势和洞察",
    "backstory":   (
        "你是一名数据驱动的分析师，擅长用统计思维解读数字。"
        "你会可视化数据，让复杂信息一目了然。"
        "你注重数据质量和分析的严谨性。"
    ),
    "tools":       ["code_execute", "file_read"],
    "default_model": "gpt-4o-mini",
    "temperature":  0.4,
}

REVIEWER = {
    "name":        "Reviewer",
    "role":        "质量审核员",
    "goal":        "审查工作成果，确保质量达标",
    "backstory":   (
        "你是一名资深 QA，见过太多粗心大意的交付。"
        "你严格把关，从不妥协质量。"
        "你的反馈建设性强，能帮助团队持续改进。"
    ),
    "tools":       ["file_read"],
    "default_model": "gpt-4o",
    "temperature":  0.1,
}

PLANNER = {
    "name":        "Planner",
    "role":        "任务规划师",
    "goal":        "将复杂任务拆解为可执行的子任务序列",
    "backstory":   (
        "你是一名项目经理，擅长将模糊的需求转化为清晰的任务计划。"
        "你考虑依赖关系、资源限制和风险。"
        "你的计划务实、可执行，有明确的时间表。"
    ),
    "tools":       [],
    "default_model": "gpt-4o",
    "temperature":  0.5,
}

DEFAULT_ROLES = {
    "researcher": RESEARCHER,
    "writer":     WRITER,
    "coder":      CODE_AGENT,
    "analyzer":   ANALYZER,
    "reviewer":   REVIEWER,
    "planner":    PLANNER,
}


# ── 数据模型 ─────────────────────────────────────────────────────────────────

@dataclass
class Role:
    """角色定义"""
    name:          str
    role:          str           # 中文角色名
    goal:          str           # 核心目标
    backstory:     str           # 背景故事（用于 prompt 构建）
    tools:         List[str]     # 可用工具列表
    default_model: str = "gpt-4o"
    temperature:   float = 0.5
    max_tokens:    int = 4096
    extra:         Dict[str, Any] = field(default_factory=dict)

    def to_prompt(self) -> str:
        """将角色转化为 LLM prompt"""
        tools_str = ", ".join(self.tools) if self.tools else "（无预置工具）"
        return (
            f"【角色】{self.role}\n"
            f"【目标】{self.goal}\n"
            f"【背景】{self.backstory}\n"
            f"【可用工具】{tools_str}\n"
        )

    def to_dict(self) -> dict:
        return {
            "name":          self.name,
            "role":          self.role,
            "goal":          self.goal,
            "backstory":     self.backstory,
            "tools":         self.tools,
            "default_model": self.default_model,
            "temperature":   self.temperature,
            "max_tokens":    self.max_tokens,
            **self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Role":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            **{k: v for k, v in data.items() if k in known},
            extra=extra,
        )


@dataclass
class AgentProfile:
    """Agent 实例配置"""
    id:          str
    name:        str
    role:        Role
    model:       str           = "gpt-4o"
    temperature: float = 0.5
    max_tokens:  int = 4096
    memory_enabled: bool = True   # 是否启用记忆
    tools:       List[str] = field(default_factory=list)  # 实例级工具覆盖
    metadata:    Dict[str, Any] = field(default_factory=dict)

    def system_prompt(self) -> str:
        """生成系统提示词"""
        return self.role.to_prompt()

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "name":           self.name,
            "role":           self.role.name,
            "role_full":      self.role.to_dict(),
            "model":          self.model,
            "temperature":    self.temperature,
            "max_tokens":     self.max_tokens,
            "memory_enabled": self.memory_enabled,
            "tools":          self.tools or self.role.tools,
            "metadata":       self.metadata,
            "created_at":     datetime.now().isoformat(),
        }


# ── 角色注册表 ──────────────────────────────────────────────────────────────

class RoleRegistry:
    """
    全局角色注册表：
    - 管理预定义角色
    - 注册自定义角色
    - 创建 Agent 实例
    """

    def __init__(self):
        self._roles: Dict[str, Role] = {}
        # 加载预定义角色
        for key, data in DEFAULT_ROLES.items():
            self._roles[key] = Role.from_dict(data)

    # ── 角色管理 ───────────────────────────────────────────────────────────

    def register(self, key: str, role: Role) -> None:
        """注册或更新角色"""
        self._roles[key] = role
        print(f"✅ Registered role: {key} ({role.role})")

    def get(self, key: str) -> Optional[Role]:
        """获取角色"""
        return self._roles.get(key)

    def list_roles(self) -> List[str]:
        """列出所有角色"""
        return list(self._roles.keys())

    def load_from_file(self, filepath: str) -> int:
        """从 JSON 文件加载角色"""
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for item in data:
                key = item.pop("_key", item.get("name", "unknown").lower())
                self._roles[key] = Role.from_dict(item)
        elif isinstance(data, dict):
            for key, item in data.items():
                self._roles[key] = Role.from_dict(item)
        return len(self._roles)

    def save_to_file(self, filepath: str) -> None:
        """保存角色到 JSON 文件"""
        data = {k: v.to_dict() for k, v in self._roles.items()
                if k not in DEFAULT_ROLES}  # 只保存自定义角色
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── Agent 创建 ────────────────────────────────────────────────────────

    def create_agent(
        self,
        agent_id: str,
        role_key: str,
        model: str = None,
        temperature: float = None,
        memory_enabled: bool = True,
        **kwargs,
    ) -> AgentProfile:
        """
        从角色创建 Agent 实例

        Args:
            agent_id:  Agent 唯一 ID
            role_key:  角色键（如 "researcher", "writer"）
            model:     指定模型（覆盖角色默认）
            temperature: 指定温度（覆盖角色默认）
            memory_enabled: 是否启用记忆
        """
        role = self._roles.get(role_key)
        if not role:
            raise ValueError(f"Unknown role: {role_key}. Available: {self.list_roles()}")

        return AgentProfile(
            id=agent_id,
            name=agent_id,
            role=role,
            model=model or role.default_model,
            temperature=temperature if temperature is not None else role.temperature,
            max_tokens=role.max_tokens,
            memory_enabled=memory_enabled,
            **kwargs,
        )

    # ── 预设团队 ──────────────────────────────────────────────────────────

    def create_research_team(self, prefix: str = "team") -> List[AgentProfile]:
        """创建标准研究团队：研究员 + 写手 + 审核"""
        return [
            self.create_agent(f"{prefix}_researcher", "researcher"),
            self.create_agent(f"{prefix}_writer",     "writer"),
            self.create_agent(f"{prefix}_reviewer",   "reviewer"),
        ]

    def create_dev_team(self, prefix: str = "team") -> List[AgentProfile]:
        """创建标准开发团队：规划师 + 工程师 + 审核"""
        return [
            self.create_agent(f"{prefix}_planner",  "planner"),
            self.create_agent(f"{prefix}_coder",     "coder"),
            self.create_agent(f"{prefix}_reviewer", "reviewer"),
        ]


# ── 全局单例 ──────────────────────────────────────────────────────────────

_global_registry: Optional[RoleRegistry] = None

def get_registry() -> RoleRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = RoleRegistry()
        # 尝试加载自定义角色文件
        custom_path = os.environ.get("CLAWSWARM_ROLES_FILE")
        if custom_path and os.path.exists(custom_path):
            _global_registry.load_from_file(custom_path)
    return _global_registry


# ── CLI 入口 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    reg = get_registry()
    parser = argparse.ArgumentParser(description="ClawSwarm Role Manager")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="列出所有角色")
    sub.add_parser("team", help="显示预设团队")

    p = sub.add_parser("create", help="创建 Agent 实例")
    p.add_argument("agent_id")
    p.add_argument("role_key")
    p.add_argument("--model")
    p.add_argument("--temperature", type=float)

    p = sub.add_parser("export", help="导出自定义角色到文件")
    p.add_argument("filepath")

    p = sub.add_parser("import", help="从文件导入角色")
    p.add_argument("filepath")

    args = parser.parse_args(sys.argv[1:])

    if args.cmd == "list":
        print("可用角色:")
        for k, v in reg._roles.items():
            print(f"  {k:12s}  {v.role}  tools={v.tools}")

    elif args.cmd == "team":
        print("预设研究团队:")
        for a in reg.create_research_team():
            print(f"  {a.id:30s}  role={a.role.role}  model={a.model}  memory={a.memory_enabled}")

    elif args.cmd == "create":
        agent = reg.create_agent(
            args.agent_id, args.role_key,
            model=args.model, temperature=args.temperature,
        )
        print(f"Agent created: {agent.id}")
        print(f"  Role:   {agent.role.role}")
        print(f"  Goal:   {agent.role.goal}")
        print(f"  Model:  {agent.model}")
        print(f"  Memory: {agent.memory_enabled}")
        print(f"\nSystem Prompt:\n{agent.system_prompt()}")

    elif args.cmd == "export":
        reg.save_to_file(args.filepath)
        print(f"✅ 自定义角色已导出到 {args.filepath}")

    elif args.cmd == "import":
        n = reg.load_from_file(args.filepath)
        print(f"✅ 导入 {n} 个角色")

    else:
        parser.print_help()
